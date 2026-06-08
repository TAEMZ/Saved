# Deployment Checklist for Reminder Bot

## Critical: Set Up Reminder Cron Job

Your bot needs an external cron service to check for due reminders every minute.

### Option 1: cron-job.org (Recommended - Free)
1. Go to https://cron-job.org and create a free account
2. Create a new cron job with these settings:
   - **Title:** "Saved Messages Reminder Checker"
   - **URL:** `https://YOUR_APP_NAME.onrender.com/check_reminders?token=sare_secret_token_98351`
   - **Schedule:** Every 1 minute (*/1 * * * *)
   - **HTTP Method:** GET
3. Save and enable the job

### Option 2: EasyCron (Free tier available)
1. Go to https://www.easycron.com
2. Create cron job with URL: `https://YOUR_APP_NAME.onrender.com/check_reminders?token=sare_secret_token_98351`
3. Schedule: Every minute

### Option 3: UptimeRobot (Free monitoring with side effect of triggering reminders)
1. Go to https://uptimerobot.com
2. Add new monitor:
   - Monitor Type: HTTP(s)
   - URL: `https://YOUR_APP_NAME.onrender.com/check_reminders?token=sare_secret_token_98351`
   - Monitoring Interval: 1 minute
   
## Verify Reminders Are Working

1. Save a message in the bot
2. Set a reminder for "in 2 minutes"
3. Wait 2-3 minutes
4. You should receive the reminder

If not working, check:
- Cron job is enabled and running
- URL is correct (replace YOUR_APP_NAME with your actual Render app name)
- Token matches the one in your config.json (default: sare_secret_token_98351)

## New Features Added

### Better Date Parsing
You can now schedule reminders for:
- Minutes: `in 5m`, `in 30 minutes`
- Hours: `in 2h`, `in 6 hours`
- Days: `in 3 days`
- **Weeks: `in 2 weeks`, `in 1 week`**
- **Months: `in 3 months`, `in 1 month`**
- **Years: `in 1 year`**
- Specific dates: `tomorrow 3pm`, `next friday`, `june 15th 2pm`

### Media File Viewing
- Photos, videos, documents, audio, and voice messages now display when you use `/view<id>`
- If the original message can't be copied, the bot sends the media using the stored file ID
