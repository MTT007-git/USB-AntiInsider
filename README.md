# USB-AntiInsider

Remotely watch and control USB drives through a Telegram bot.

- Instantly see USB drives plugged in and out
- Monitor changes made to files
- Ignore changes from system or custom folders
- Lock and unlock USB drives or files and folders
- Look at the filesystem and download/upload files
- Safe authorization for multiple chats

## Before use

1. Clone the repo `git clone https://github.com/MTT007-git/USB-AntiInsider.git`
2. Install dependencies `pip install -r requirements.txt`
3. Rename `.env.example` to `.env`
4. Replace example values with actual values (see comments for details)
5. Remove all comments (`#`)
6. In `/server`, run:
   ```cmd
   flask db init
   flask db migrate
   flask db upgrade
   ```
7. Create a Telegram bot using **BotFather**
8. Add commands (optional)

## How to use

Run `server/app.py` on a server

Run `client/main.py` on the client machines (it will ask for administrator if it doesn't have it)

## Commands
- /start - Start monitoring
- /stop - Stop monitoring
- /lock `letter` - Make drive `letter` read-only
- /release `letter` - Make drive `letter` non-read-only
- /lockfile `path` - Make a file/folder read-only
- /releasefile `path` - Make a file/folder non-read-only
- /ignorelist - List all ignored regex patterns
- /ignoreadd `regex` - Add regex pattern `regex` to ignore
- /ignoredel `regex` - Remove ignored regex pattern `regex`
- /ignoreedit `index` `regex` - Edit ignored regex pattern at `index` to `regex`
- /listdir `folder_path` - List the contents of directory `folder_path`
- /download `file_path` - Download file `file_path`
- /upload `file_path` with a file - Upload file at `file_path`
- /auth `key` - Authorize the current chat if `key` is correct
- /deauth - Deauthorize everyone
- /help - List all commands

## Autorun on startup

1. Open **Task Scheduler**
2. Menu - Action - Create task
3. Name: `AntiInsider`
4. Run with highest privileges: `True` **- important**
5. Configure for: `Windows 10` (or your Windows version)
6. Triggers - New
    - Begin the task: `At startup`
7. Actions - New
    - Action: `Start a program`
    - Program/script: `C:/path/to/Python/pythonw.exe` (or `python.exe`)
    - Add arguments: `C:/path/to/script/main.py`
8. Conditions - Start the task only if the computer is on AC power: `False`
9. Settings
    - Run task as soon as possible after a scheduled restart is missed: `True`
    - Stop the task if it runs longer than: `False`
    - If the task is already running, then the following rule applies: `Do not start a new instance`
