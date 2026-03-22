import json
import os
import argparse
import urllib.request
import urllib.parse
from datetime import datetime, timedelta


def _load_env(path=".env"):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

_load_env()

META_API_VERSION = "v19.0"
BASE_URL = "https://graph.facebook.com/{}".format(META_API_VERSION)

FIELDS = "campaign_name,spend,impressions,clicks,ctr,cpc,cpm,actions"


def fetch_insights(account_id, access_token, since, until, level, breakdown=None):
    params = {
        "access_token": access_token,
        "fields": FIELDS,
        "level": level,
        "time_range": json.dumps({"since": since, "until": until}),
        "limit": 500,
    }
    if breakdown:
        params["breakdowns"] = breakdown

    url = "{}/{}/insights?{}".format(BASE_URL, account_id, urllib.parse.urlencode(params))
    with urllib.request.urlopen(url) as response:
        data = json.loads(response.read().decode())

    insights = data.get("data", [])
    return {"result": {"insights": insights}}


def main():
    parser = argparse.ArgumentParser(description="Fetch Meta Ads data and save as JSON files.")
    parser.add_argument("--account_id", required=True, help="Meta ad account ID (e.g., act_123456789)")
    parser.add_argument("--access_token", default=os.environ.get("META_ACCESS_TOKEN"), help="Meta API access token (or set META_ACCESS_TOKEN env var)")
    parser.add_argument("--start_date", help="Start date YYYY-MM-DD (default: 7 days ago)")
    parser.add_argument("--end_date", help="End date YYYY-MM-DD (default: yesterday)")
    parser.add_argument("--output_dir", default=".", help="Directory to save JSON files (default: current directory)")
    args = parser.parse_args()

    if not args.access_token:
        raise EnvironmentError("Provide --access_token or set META_ACCESS_TOKEN environment variable.")

    since = args.start_date or (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    until = args.end_date or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    out = os.path.realpath(args.output_dir)

    print("Fetching campaign data...")
    campaign_data = fetch_insights(args.account_id, args.access_token, since, until, level="campaign")
    campaign_file = os.path.join(out, "campaign.json")
    with open(campaign_file, "w") as f:
        json.dump(campaign_data, f, indent=2)
    print("  Saved: {}".format(campaign_file))

    print("Fetching publisher platform data...")
    publisher_data = fetch_insights(args.account_id, args.access_token, since, until, level="ad", breakdown="publisher_platform")
    publisher_file = os.path.join(out, "publisher.json")
    with open(publisher_file, "w") as f:
        json.dump(publisher_data, f, indent=2)
    print("  Saved: {}".format(publisher_file))

    print("Fetching gender data...")
    gender_data = fetch_insights(args.account_id, args.access_token, since, until, level="ad", breakdown="gender")
    gender_file = os.path.join(out, "gender.json")
    with open(gender_file, "w") as f:
        json.dump(gender_data, f, indent=2)
    print("  Saved: {}".format(gender_file))

    print("\nDone! Now run:")
    print("python weekly_meta_ads_report.py --account_id {} --start_date {} --end_date {} --campaign_data_file {} --publisher_data_file {} --gender_data_file {}".format(
        args.account_id, since, until, campaign_file, publisher_file, gender_file))


if __name__ == "__main__":
    main()
