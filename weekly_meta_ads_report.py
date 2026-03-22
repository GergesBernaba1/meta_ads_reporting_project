import json
import os
import shlex
import argparse
from datetime import datetime, timedelta

import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def send_email(to_email, subject, body, attachment_path=None):
    smtp_server = "smtp.gmail.com"
    smtp_port = 587
    sender_email = os.environ.get("SMTP_EMAIL")
    sender_password = os.environ.get("SMTP_PASSWORD")

    if not sender_email or not sender_password:
        raise EnvironmentError("SMTP_EMAIL and SMTP_PASSWORD environment variables must be set.")

    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    if attachment_path:
        safe_path = os.path.realpath(attachment_path)
        with open(safe_path, "r") as f:
            attachment = MIMEText(f.read(), "markdown")
            attachment.add_header("Content-Disposition", "attachment", filename=os.path.basename(safe_path))
            msg.attach(attachment)

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
        print("Email sent successfully to {}".format(to_email))
    except Exception as e:
        print("Error sending email to {}: {}".format(to_email, e))


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _extract_leads(item):
    for action in item.get("actions", []):
        if action["action_type"] == "lead":
            return int(action["value"])
    return 0


def _parse_insights(raw, fields):
    rows = []
    for item in raw.get("result", {}).get("insights", []):
        leads = _extract_leads(item)
        row = {k: item.get(k) for k in fields}
        row["Leads"] = leads
        row["Spend"] = float(item["spend"])
        row["CPA"] = row["Spend"] / leads if leads > 0 else float("inf")
        row["CTR"] = float(item["ctr"])
        rows.append(row)
    return pd.DataFrame(rows)


def _build_campaign_df(raw):
    df = _parse_insights(raw, ["campaign_name", "impressions", "clicks", "cpc", "cpm"])
    df.rename(columns={"campaign_name": "Name", "impressions": "Impressions",
                        "clicks": "Clicks_all", "cpc": "CPC", "cpm": "CPM"}, inplace=True)
    df["Impressions"] = df["Impressions"].astype(int)
    df["Clicks_all"] = df["Clicks_all"].astype(int)
    df["CPC"] = df["CPC"].astype(float)
    df["CPM"] = df["CPM"].astype(float)
    return df[["Name", "Spend", "Impressions", "Clicks_all", "Leads", "CTR", "CPC", "CPA", "CPM"]]


def _build_breakdown_df(raw, breakdown_col, breakdown_key):
    df = _parse_insights(raw, ["campaign_name", breakdown_key])
    df.rename(columns={"campaign_name": "Campaign", breakdown_key: breakdown_col}, inplace=True)
    df[breakdown_col] = df[breakdown_col].fillna("unknown")
    return df[["Campaign", breakdown_col, "Spend", "Leads", "CPA", "CTR"]]


def _agg_breakdown(df, breakdown_col):
    return (
        df.groupby(["Campaign", breakdown_col])
        .agg(Spend=("Spend", "sum"), Leads=("Leads", "sum"), CTR=("CTR", "mean"))
        .assign(CPA=lambda x: x["Spend"] / x["Leads"].replace(0, float("nan")))
        .fillna(float("inf"))
    )


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def _best(df, col):
    valid = df[df["Leads"] > 0]
    return valid.loc[valid["CPA"].idxmin()] if not valid.empty else None


def _worst(df):
    return df.loc[df["CPA"].idxmax()]


def generate_report_content(ad_account_id, start_date, end_date, campaign_data_raw, publisher_data_raw, gender_data_raw, output_dir=None):
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    df_campaigns = _build_campaign_df(campaign_data_raw)
    df_publishers = _build_breakdown_df(publisher_data_raw, "Platform", "publisher_platform")
    df_genders = _build_breakdown_df(gender_data_raw, "Gender", "gender")

    df_pub_agg = _agg_breakdown(df_publishers, "Platform")
    df_gen_agg = _agg_breakdown(df_genders, "Gender")

    total_spend = df_campaigns["Spend"].sum()
    total_leads = df_campaigns["Leads"].sum()
    overall_cpa = total_spend / total_leads if total_leads > 0 else float("inf")
    overall_ctr = (df_campaigns["Clicks_all"].sum() / df_campaigns["Impressions"].sum()) * 100 if df_campaigns["Impressions"].sum() > 0 else 0

    best_camp = _best(df_campaigns, "Name")
    worst_camp = _worst(df_campaigns)
    best_plat = _best(df_pub_agg.reset_index(), "Platform")
    worst_plat = _worst(df_pub_agg.reset_index())
    best_gen = _best(df_gen_agg.reset_index(), "Gender")
    worst_gen = _worst(df_gen_agg.reset_index())

    lines = [
        "# Meta Ads Performance Review: {} ({} to {})\n".format(ad_account_id, start_str, end_str),
        "## Executive Summary\n",
        "The account spent **{:.2f} EGP** and generated **{} Leads** from {} to {}. "
        "Overall CPA: **{:.2f} EGP** | Average CTR: **{:.2f}%**.\n".format(
            total_spend, total_leads, start_str, end_str, overall_cpa, overall_ctr),
        "## What's Working (Top Performers)\n",
    ]

    if best_camp is not None:
        lines.append("- **Most Efficient Campaign:** \"{}\" — CPA {:.2f} EGP\n".format(best_camp["Name"], best_camp["CPA"]))
    if best_plat is not None:
        lines.append("- **Most Efficient Platform:** \"{}\" in \"{}\" — CPA {:.2f} EGP\n".format(
            best_plat["Platform"], best_plat["Campaign"], best_plat["CPA"]))
    if best_gen is not None:
        lines.append("- **Most Efficient Gender Segment:** \"{}\" in \"{}\" — CPA {:.2f} EGP\n".format(
            best_gen["Gender"], best_gen["Campaign"], best_gen["CPA"]))

    lines.append("\n## What's Wasting Budget (Inefficiencies)\n")

    def _inefficiency_line(label, name, cpa):
        if cpa == float("inf"):
            return "- **{}:** \"{}\" generated no leads.\n".format(label, name)
        return "- **{}:** \"{}\" — CPA {:.2f} EGP\n".format(label, name, cpa)

    lines.append(_inefficiency_line("Least Efficient Campaign", worst_camp["Name"], worst_camp["CPA"]))
    lines.append(_inefficiency_line("Least Efficient Platform",
                                    "{} / {}".format(worst_plat["Campaign"], worst_plat["Platform"]), worst_plat["CPA"]))
    lines.append(_inefficiency_line("Least Efficient Gender Segment",
                                    "{} / {}".format(worst_gen["Campaign"], worst_gen["Gender"]), worst_gen["CPA"]))

    lines += [
        "\n## Campaign Performance Breakdown\n",
        df_campaigns.to_markdown(index=False) + "\n",
        "\n## Publisher Platform Performance\n",
        df_pub_agg.to_markdown() + "\n",
        "\n## Gender Performance\n",
        df_gen_agg.to_markdown() + "\n",
        "\n## Actionable Next Steps\n",
        "Based on the performance data, consider the following:\n",
    ]

    step = 1
    if best_camp is not None:
        lines.append("{}. **Scale \"{}\" (CPA: {:.2f} EGP):** Most efficient campaign — gradually increase budget while monitoring CPA.\n".format(
            step, best_camp["Name"], best_camp["CPA"]))
        step += 1

    if worst_camp["CPA"] == float("inf"):
        lines.append("{}. **Review \"{}\" (No Leads):** Investigate creative, targeting, and offer. Consider pausing if no improvement.\n".format(
            step, worst_camp["Name"]))
    else:
        lines.append("{}. **Optimize \"{}\" (CPA: {:.2f} EGP):** Review creatives, targeting, and landing page to reduce CPA.\n".format(
            step, worst_camp["Name"], worst_camp["CPA"]))
    step += 1

    if best_plat is not None and best_plat["Platform"] != worst_plat["Platform"]:
        lines.append("{}. **Shift budget to \"{}\" from \"{}\" (CPA: {:.2f} vs {:.2f} EGP):** Reallocate within relevant campaigns.\n".format(
            step, best_plat["Platform"], worst_plat["Platform"], best_plat["CPA"], worst_plat["CPA"]))
        step += 1

    if best_gen is not None and best_gen["Gender"] != worst_gen["Gender"]:
        lines.append("{}. **Refine gender targeting — focus on \"{}\" (CPA: {:.2f} EGP); review \"{}\" (CPA: {:.2f} EGP).**\n".format(
            step, best_gen["Gender"], best_gen["CPA"], worst_gen["Gender"], worst_gen["CPA"]))

    report_content = "\n".join(lines)
    report_filename = "meta_ads_report_{}_{}.md".format(ad_account_id, end_str)
    base_dir = os.path.realpath(output_dir) if output_dir else os.path.realpath(os.getcwd())
    report_path = os.path.join(base_dir, report_filename)

    with open(report_path, "w") as f:
        f.write(report_content)

    return report_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate and send Meta Ads performance reports.")
    parser.add_argument("--account_id", type=str, required=True, help="Ad account ID (e.g., act_123456789).")
    parser.add_argument("--start_date", type=str, help="Start date YYYY-MM-DD (default: 7 days ago).")
    parser.add_argument("--end_date", type=str, help="End date YYYY-MM-DD (default: yesterday).")
    parser.add_argument("--email", type=str, default="gergesbernaba2@gmail.com", help="Recipient email.")
    parser.add_argument("--campaign_data_file", type=str, help="Path to campaign data JSON.")
    parser.add_argument("--publisher_data_file", type=str, help="Path to publisher data JSON.")
    parser.add_argument("--gender_data_file", type=str, help="Path to gender data JSON.")
    parser.add_argument("--output_dir", type=str, default=None, help="Directory to save the report (default: cwd).")

    args = parser.parse_args()

    ad_account_id = args.account_id
    start_date = datetime.fromisoformat(args.start_date) if args.start_date else datetime.now() - timedelta(days=7)
    end_date = datetime.fromisoformat(args.end_date) if args.end_date else datetime.now() - timedelta(days=1)

    if args.campaign_data_file and args.publisher_data_file and args.gender_data_file:
        with open(os.path.realpath(args.campaign_data_file)) as f:
            campaign_data_raw = json.load(f)
        with open(os.path.realpath(args.publisher_data_file)) as f:
            publisher_data_raw = json.load(f)
        with open(os.path.realpath(args.gender_data_file)) as f:
            gender_data_raw = json.load(f)

        print("Generating report for {} ({} to {})".format(
            ad_account_id, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")))
        report_file = generate_report_content(
            ad_account_id, start_date, end_date,
            campaign_data_raw, publisher_data_raw, gender_data_raw,
            output_dir=args.output_dir
        )

        subject = "Meta Ads Performance Report for {} ({} to {})".format(
            ad_account_id, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
        body = "Dear User,\n\nPlease find attached your Meta Ads performance report for account {}.\n\nBest regards,\nMeta Ads Reporter".format(ad_account_id)
        send_email(args.email, subject, body, report_file)
    else:
        date_range = {"since": start_date.strftime("%Y-%m-%d"), "until": end_date.strftime("%Y-%m-%d")}
        print("MCP_COMMAND_START")
        print("manus-mcp-cli tool call meta_marketing_get_insights --server meta-marketing --input {}".format(
            shlex.quote(json.dumps({"object_type": "ad_account", "object_id": ad_account_id, "level": "campaign", "date_range": date_range}))))
        print("manus-mcp-cli tool call meta_marketing_get_insights --server meta-marketing --input {}".format(
            shlex.quote(json.dumps({"object_type": "ad_account", "object_id": ad_account_id, "level": "ad", "date_range": date_range, "breakdown": "publisher_platform"}))))
        print("manus-mcp-cli tool call meta_marketing_get_insights --server meta-marketing --input {}".format(
            shlex.quote(json.dumps({"object_type": "ad_account", "object_id": ad_account_id, "level": "ad", "date_range": date_range, "breakdown": "gender"}))))
        print("MCP_COMMAND_END")


if __name__ == "__main__":
    main()
