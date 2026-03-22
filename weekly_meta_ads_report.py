import json
import pandas as pd
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import subprocess
import argparse
import re
import os
import shlex

def send_email(to_email, subject, body, attachment_path=None):
    smtp_server = "smtp.gmail.com"
    smtp_port = 587
    sender_email = "your_email@gmail.com"
    sender_password = "your_password"

    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = to_email
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    if attachment_path:
        with open(attachment_path, "r") as f:
            attachment = MIMEText(f.read(), "markdown")
            attachment.add_header("Content-Disposition", "attachment", filename=attachment_path.split("/")[-1])
            msg.attach(attachment)

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
        print("Email sent successfully to {}".format(to_email))
    except Exception as e:
        print("Error sending email to {}: {}".format(to_email, e))

def generate_report_content(ad_account_id, start_date, end_date, campaign_data_raw, publisher_data_raw, gender_data_raw):
    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")

    campaign_data = campaign_data_raw.get("result", {}).get("insights", [])
    publisher_data = publisher_data_raw.get("result", {}).get("insights", [])
    gender_data = gender_data_raw.get("result", {}).get("insights", [])

    campaigns = []
    for item in campaign_data:
        leads = 0
        for action in item.get("actions", []):
            if action["action_type"] == "lead":
                leads = int(action["value"])
                break
        
        campaigns.append({
            "Name": item["campaign_name"],
            "Spend": float(item["spend"]),
            "Impressions": int(item["impressions"]),
            "Clicks_all": int(item["clicks"]),
            "Leads": leads,
            "CTR": float(item["ctr"]),
            "CPC": float(item["cpc"]),
            "CPA": float(item["spend"]) / leads if leads > 0 else float("inf"),
            "CPM": float(item["cpm"])
        })
    
    df_campaigns = pd.DataFrame(campaigns)

    publishers = []
    for item in publisher_data:
        leads = 0
        for action in item.get("actions", []):
            if action["action_type"] == "lead":
                leads = int(action["value"])
                break
        
        publishers.append({
            "Campaign": item["campaign_name"],
            "Platform": item.get("publisher_platform", "unknown"),
            "Spend": float(item["spend"]),
            "Leads": leads,
            "CPA": float(item["spend"]) / leads if leads > 0 else float("inf"),
            "CTR": float(item["ctr"])
        })
    
    df_publishers = pd.DataFrame(publishers)

    genders = []
    for item in gender_data:
        leads = 0
        for action in item.get("actions", []):
            if action["action_type"] == "lead":
                leads = int(action["value"])
                break
        
        genders.append({
            "Campaign": item["campaign_name"],
            "Gender": item.get("gender", "unknown"),
            "Spend": float(item["spend"]),
            "Leads": leads,
            "CPA": float(item["spend"]) / leads if leads > 0 else float("inf"),
            "CTR": float(item["ctr"])
        })
    
    df_genders = pd.DataFrame(genders)

    summary_text = ""
    recommendations_text = ""

    total_spend = df_campaigns["Spend"].sum()
    total_leads = df_campaigns["Leads"].sum()
    overall_cpa = total_spend / total_leads if total_leads > 0 else float("inf")
    overall_ctr = (df_campaigns["Clicks_all"].sum() / df_campaigns["Impressions"].sum()) * 100 if df_campaigns["Impressions"].sum() > 0 else 0

    summary_text += "## Executive Summary\n\n"
    summary_text += "The account spent a total of **{:.2f} EGP** and generated **{} Leads** from {} to {}. The overall Cost Per Lead (CPA) was **{:.2f} EGP** and the average Click-Through Rate (CTR) was **{:.2f}%**.\n\n".format(total_spend, total_leads, start_date_str, end_date_str, overall_cpa, overall_ctr)

    summary_text += "## What\"s Working (Top Performers)\n\n"
    if not df_campaigns.empty and not df_campaigns[df_campaigns["Leads"] > 0].empty:
        best_campaign = df_campaigns[df_campaigns["Leads"] > 0].loc[df_campaigns[df_campaigns["Leads"] > 0]["CPA"].idxmin()]
        summary_text += "- **Most Efficient Campaign:** The campaign \"{}\" achieved the lowest CPA of {:.2f} EGP.\n".format(best_campaign["Name"], best_campaign["CPA"])

    df_publishers_agg = df_publishers.groupby(["Campaign", "Platform"]).agg(
        Spend=("Spend", "sum"),
        Leads=("Leads", "sum"),
        CTR=("CTR", "mean")
    ).assign(CPA=lambda x: x["Spend"] / x["Leads"])
    df_publishers_agg = df_publishers_agg.reset_index()

    if not df_publishers_agg.empty and not df_publishers_agg[df_publishers_agg["Leads"] > 0].empty:
        best_platform = df_publishers_agg[df_publishers_agg["Leads"] > 0].loc[df_publishers_agg[df_publishers_agg["Leads"] > 0]["CPA"].idxmin()]
        summary_text += "- **Most Efficient Platform:** \"{}\" in campaign \"{}\" delivered leads at {:.2f} EGP.\n\n".format(best_platform["Platform"], best_platform["Campaign"], best_platform["CPA"])

    df_genders_agg = df_genders.groupby(["Campaign", "Gender"]).agg(
        Spend=("Spend", "sum"),
        Leads=("Leads", "sum"),
        CTR=("CTR", "mean")
    ).assign(CPA=lambda x: x["Spend"] / x["Leads"])
    df_genders_agg = df_genders_agg.reset_index()

    if not df_genders_agg.empty and not df_genders_agg[df_genders_agg["Leads"] > 0].empty:
        best_gender = df_genders_agg[df_genders_agg["Leads"] > 0].loc[df_genders_agg[df_genders_agg["Leads"] > 0]["CPA"].idxmin()]
        summary_text += "- **Most Efficient Gender Segment:** \"{}\" in campaign \"{}\" had a CPA of {:.2f} EGP.\n\n".format(best_gender["Gender"], best_gender["Campaign"], best_gender["CPA"])

    summary_text += "## What\"s Wasting Budget (Inefficiencies)\n\n"
    if not df_campaigns.empty:
        worst_campaign = df_campaigns.loc[df_campaigns["CPA"].idxmax()]
        if worst_campaign["CPA"] == float("inf"):
            summary_text += "- **Least Efficient Campaign:** The campaign \"{}\" generated no leads, indicating potential budget waste.\n".format(worst_campaign["Name"])
        else:
            summary_text += "- **Least Efficient Campaign:** The campaign \"{}\" had the highest CPA of {:.2f} EGP.\n".format(worst_campaign["Name"], worst_campaign["CPA"])

    if not df_publishers_agg.empty:
        worst_platform = df_publishers_agg.loc[df_publishers_agg["CPA"].idxmax()]
        if worst_platform["CPA"] == float("inf"):
            summary_text += "- **Least Efficient Platform:** \"{}\" in campaign \"{}\" generated no leads.\n".format(worst_platform["Platform"], worst_platform["Campaign"])
        else:
            summary_text += "- **Least Efficient Platform:** \"{}\" in campaign \"{}\" had the highest CPA of {:.2f} EGP.\n".format(worst_platform["Platform"], worst_platform["Campaign"], worst_platform["CPA"])

    if not df_genders_agg.empty:
        worst_gender = df_genders_agg.loc[df_genders_agg["CPA"].idxmax()]
        if worst_gender["CPA"] == float("inf"):
            summary_text += "- **Least Efficient Gender Segment:** \"{}\" in campaign \"{}\" generated no leads.\n\n".format(worst_gender["Gender"], worst_gender["Campaign"])
        else:
            summary_text += "- **Least Efficient Gender Segment:** \"{}\" in campaign \"{}\" had the highest CPA of {:.2f} EGP.\n\n".format(worst_gender["Gender"], worst_gender["Campaign"], worst_gender["CPA"])

    recommendations_text += "## Actionable Next Steps\n\n"
    recommendations_text += "Based on the performance data, consider the following actionable steps:\n\n"

    if not df_campaigns.empty and not df_campaigns[df_campaigns["Leads"] > 0].empty:
        best_campaign = df_campaigns[df_campaigns["Leads"] > 0].loc[df_campaigns[df_campaigns["Leads"] > 0]["CPA"].idxmin()]
        recommendations_text += "1. **Increase Budget for \"{}\" (CPA: {:.2f} EGP):** This campaign is currently the most efficient in generating leads. Consider gradually increasing its budget to scale performance, while closely monitoring CPA.\n\n".format(best_campaign["Name"], best_campaign["CPA"])

    if not df_campaigns.empty:
        worst_campaign = df_campaigns.loc[df_campaigns["CPA"].idxmax()]
        if worst_campaign["CPA"] == float("inf"):
            recommendations_text += "2. **Review \"{}\" (No Leads):** This campaign is not generating any leads. Investigate creative, targeting, and offer to identify the root cause. Consider pausing or re-strategizing if no improvements are seen.\n\n".format(worst_campaign["Name"])
        else:
            recommendations_text += "2. **Optimize \"{}\" (CPA: {:.2f} EGP):** With a higher CPA, this campaign needs attention. Review ad creatives, targeting, and landing page experience to improve conversion rates and reduce CPA.\n\n".format(worst_campaign["Name"], worst_campaign["CPA"])

    if not df_publishers_agg.empty and not df_publishers_agg[df_publishers_agg["Leads"] > 0].empty:
        best_platform = df_publishers_agg[df_publishers_agg["Leads"] > 0].loc[df_publishers_agg[df_publishers_agg["Leads"] > 0]["CPA"].idxmin()]
        worst_platform = df_publishers_agg.loc[df_publishers_agg["CPA"].idxmax()]
        if best_platform["Platform"] != worst_platform["Platform"]:
            recommendations_text += "3. **Shift Budget to \"{}\" from \"{}\" (CPA: {:.2f} EGP vs {:.2f} EGP):** The \"{}\" platform is significantly more efficient. Consider reallocating budget from \"{}\" to \"{}\" within the relevant campaigns.\n\n".format(best_platform["Platform"], worst_platform["Platform"], best_platform["CPA"], worst_platform["CPA"], best_platform["Platform"], worst_platform["Platform"], best_platform["Platform"])

    if not df_genders_agg.empty and not df_genders_agg[df_genders_agg["Leads"] > 0].empty:
        best_gender = df_genders_agg[df_genders_agg["Leads"] > 0].loc[df_genders_agg[df_genders_agg["Leads"] > 0]["CPA"].idxmin()]
        worst_gender = df_genders_agg.loc[df_genders_agg["CPA"].idxmax()]
        if best_gender["Gender"] != worst_gender["Gender"]:
            recommendations_text += "4. **Refine Gender Targeting (Best: \"{}\" at {:.2f} EGP; Worst: \"{}\" at {:.2f} EGP):** Focus more budget on the \"{}\" segment, which shows better CPA. For the \"{}\" segment, test different creatives or adjust targeting to improve efficiency.\n\n".format(best_gender["Gender"], best_gender["CPA"], worst_gender["Gender"], worst_gender["CPA"], best_gender["Gender"], worst_gender["Gender"])

    report_content = "# Meta Ads Performance Review: {} ({} to {})".format(ad_account_id, start_date_str, end_date_str)
    report_content += summary_text
    report_content += "\n## Campaign Performance Breakdown\n"
    report_content += df_campaigns.to_markdown(index=False) + "\n\n"

    report_content += "## Publisher Platform Performance\n"
    report_content += df_publishers.groupby(["Campaign", "Platform"]).agg({
        "Spend": "sum",
        "Leads": "sum",
        "CTR": "mean"
    }).assign(CPA=lambda x: x["Spend"] / x["Leads"]).to_markdown() + "\n\n"

    report_content += "## Gender Performance\n"
    report_content += df_genders.groupby(["Campaign", "Gender"]).agg({
        "Spend": "sum",
        "Leads": "sum",
        "CTR": "mean"
    }).assign(CPA=lambda x: x["Spend"] / x["Leads"]).to_markdown() + "\n\n"
    report_content += recommendations_text

    report_filename = "meta_ads_report_{}_{}.md".format(ad_account_id, end_date_str)
    report_path = "/home/ubuntu/{}".format(report_filename)
    with open(report_path, "w") as f:
        f.write(report_content)
    
    return report_path

def main():
    parser = argparse.ArgumentParser(description="Generate and send Meta Ads performance reports.")
    parser.add_argument("--account_id", type=str, help="Specific ad account ID to generate report for (e.g., act_123456789).")
    parser.add_argument("--start_date", type=str, help="Start date for the report in YYYY-MM-DD format.")
    parser.add_argument("--end_date", type=str, help="End date for the report in YYYY-MM-DD format.")
    parser.add_argument("--email", type=str, default="gergesbernaba2@gmail.com", help="Email address to send the report to.")
    
    # Arguments for raw JSON data file paths
    parser.add_argument("--campaign_data_file", type=str, help="Path to raw campaign data JSON file.")
    parser.add_argument("--publisher_data_file", type=str, help="Path to raw publisher data JSON file.")
    parser.add_argument("--gender_data_file", type=str, help="Path to raw gender data JSON file.")

    args = parser.parse_args()

    target_email = args.email

    if args.account_id:
        ad_account_id = args.account_id
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d") if args.start_date else datetime.now() - timedelta(days=7)
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d") if args.end_date else datetime.now() - timedelta(days=1)
        
        # If data files are provided, read them
        if args.campaign_data_file and args.publisher_data_file and args.gender_data_file:
            with open(args.campaign_data_file, "r") as f:
                campaign_data_raw = json.load(f)
            with open(args.publisher_data_file, "r") as f:
                publisher_data_raw = json.load(f)
            with open(args.gender_data_file, "r") as f:
                gender_data_raw = json.load(f)
            
            print("Generating report for account: {} from {} to {}".format(ad_account_id, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")))
            report_file = generate_report_content(ad_account_id, start_date, end_date, campaign_data_raw, publisher_data_raw, gender_data_raw)
            
            subject = "Meta Ads Performance Report for {} ({} to {})".format(ad_account_id, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
            body = "Dear User,\n\nPlease find attached your Meta Ads performance report for the account {}.\n\nBest regards,\nManus AI".format(ad_account_id)
            send_email(target_email, subject, body, report_file)
        else:
            # Print commands for the agent to execute
            print("MCP_COMMAND_START")
            campaign_input = json.dumps({"object_type": "ad_account", "object_id": ad_account_id, "level": "campaign", "date_range": {"since": start_date.strftime("%Y-%m-%d"), "until": end_date.strftime("%Y-%m-%d") }})
            print(f"manus-mcp-cli tool call meta_marketing_get_insights --server meta-marketing --input {shlex.quote(campaign_input)}")
            
            publisher_input_data = {"object_type": "ad_account", "object_id": ad_account_id, "level": "ad", "date_range": {"since": start_date.strftime("%Y-%m-%d"), "until": end_date.strftime("%Y-%m-%d")}, "breakdown": "publisher_platform"}
            publisher_input_json = json.dumps(publisher_input_data)
            print(f"manus-mcp-cli tool call meta_marketing_get_insights --server meta-marketing --input {shlex.quote(publisher_input_json)}")
            
            gender_input_data = {"object_type": "ad_account", "object_id": ad_account_id, "level": "ad", "date_range": {"since": start_date.strftime("%Y-%m-%d"), "until": end_date.strftime("%Y-%m-%d")}, "breakdown": "gender"}
            gender_input_json = json.dumps(gender_input_data)
            print(f"manus-mcp-cli tool call meta_marketing_get_insights --server meta-marketing --input {shlex.quote(gender_input_json)}")
            print("MCP_COMMAND_END")

    else:
        # This part remains for the weekly scheduled task, fetching data internally
        # This section will be handled by the agent making explicit shell calls and passing file paths
        # For now, this branch will not be executed directly by the agent for on-demand reports.
        pass

if __name__ == "__main__":
    main()
