# Meta Ads Reporting

Generates a Markdown performance report from Meta Ads insights data and optionally emails it to a recipient.

## Requirements

```
pip install pandas tabulate
```

## Configuration

Set the following environment variables before running (required only when sending email):

```bash
export SMTP_EMAIL="your_email@gmail.com"
export SMTP_PASSWORD="your_app_password"
```

> Use a [Gmail App Password](https://support.google.com/accounts/answer/185833), not your account password.

## Usage

### Generate report from JSON data files

```bash
python weekly_meta_ads_report.py \
  --account_id act_123456789 \
  --start_date 2026-02-15 \
  --end_date 2026-03-15 \
  --campaign_data_file campaign.json \
  --publisher_data_file publisher.json \
  --gender_data_file gender.json \
  --email recipient@example.com \
  --output_dir ./reports
```

### Print MCP fetch commands (no data files provided)

```bash
python weekly_meta_ads_report.py \
  --account_id act_123456789 \
  --start_date 2026-02-15 \
  --end_date 2026-03-15
```

This prints the `manus-mcp-cli` commands needed to fetch data, wrapped between `MCP_COMMAND_START` / `MCP_COMMAND_END` markers.

## Arguments

| Argument | Required | Description |
|---|---|---|
| `--account_id` | Yes | Meta ad account ID (e.g., `act_123456789`) |
| `--start_date` | No | Report start date `YYYY-MM-DD` (default: 7 days ago) |
| `--end_date` | No | Report end date `YYYY-MM-DD` (default: yesterday) |
| `--email` | No | Recipient email address |
| `--campaign_data_file` | No | Path to campaign insights JSON |
| `--publisher_data_file` | No | Path to publisher breakdown JSON |
| `--gender_data_file` | No | Path to gender breakdown JSON |
| `--output_dir` | No | Directory to save the report (default: current directory) |

## Report Structure

The generated `.md` report includes:

- **Executive Summary** — total spend, leads, CPA, CTR
- **What's Working** — top-performing campaign, platform, and gender segment
- **What's Wasting Budget** — least efficient campaign, platform, and gender segment
- **Campaign Performance Breakdown** — table with Spend, Impressions, Clicks, Leads, CTR, CPC, CPA, CPM
- **Publisher Platform Performance** — aggregated by campaign × platform
- **Gender Performance** — aggregated by campaign × gender
- **Actionable Next Steps** — data-driven recommendations

## Input JSON Format

Each data file must follow this structure:

```json
{
  "result": {
    "insights": [
      {
        "campaign_name": "My Campaign",
        "spend": "500.00",
        "impressions": "10000",
        "clicks": "200",
        "ctr": "2.0",
        "cpc": "2.5",
        "cpm": "50.0",
        "actions": [
          { "action_type": "lead", "value": "5" }
        ]
      }
    ]
  }
}
```

Publisher and gender files additionally require `publisher_platform` or `gender` fields on each insight item.
