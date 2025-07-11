GPT Assistant — Gemini-Powered Terminal AI
GPT Assistant is a terminal-based command-line assistant that converts plain English into shell commands using Google’s Gemini API. It helps users run commands more efficiently, with built-in safety, confirmation prompts, and intelligent fallback for error correction. It supports Linux, macOS, and Windows.

Features
Gemini AI integration for generating shell commands from natural language

Auto-execution of safe commands (optional)

Confirmation prompts for risky operations (move, chmod, etc.)

Built-in blocklist for dangerous operations (e.g., rm -rf, shutdown, dd)

Automatically detects your system and preferred shell

Rate limiting for API calls to prevent overuse

Usage tracking (total calls, daily usage, etc.)

Cross-platform support (Linux/macOS/Windows)

CLI-based setup and configuration

Local config storage in ~/.config/gpt-assistant or %APPDATA%\gpt-assistant

Installation
Requirements: Python 3.7+ and pip

Clone and install the tool:

bash
Copy
Edit
git clone https://github.com/your-username/gpt-assistant.git
cd gpt-assistant
pip install .
(Optional) Add a shell alias:

For Bash/Zsh:

bash
Copy
Edit
echo "alias gpt='gpt-assistant'" >> ~/.bashrc
source ~/.bashrc
For PowerShell:

powershell
Copy
Edit
function gpt { gpt-assistant $args }
Gemini API Key Setup
Get a Gemini API key from: https://makersuite.google.com/app/apikey

You can either:

Set it during first run interactively, or

Set it as an environment variable:

bash
Copy
Edit
export GEMINI_API_KEY="your-api-key"
Usage
Basic command:

bash
Copy
Edit
gpt-assistant "list all files containing error"
Management commands:

bash
Copy
Edit
gpt-assistant --enable        # Enable the assistant
gpt-assistant --disable       # Disable the assistant
gpt-assistant --status        # View current configuration and API key state
gpt-assistant --usage         # View usage statistics
gpt-assistant --api-key       # Configure or remove API key
gpt-assistant --reset         # Reset all configuration and usage data
Example:

bash
Copy
Edit
$ gpt-assistant "create a folder and move all .jpg files into it"
Generated command: mkdir images && mv *.jpg images/
Execute this command? (y/n): y
Command executed successfully
Safety
GPT Assistant will block or warn you about:

Dangerous commands: rm -rf, del C:, format, dd, shutdown, reboot, etc.

Risky commands (with optional confirmation): chmod, chown, mv, cp, systemctl, etc.

Commands marked as dangerous will never be auto-executed. Users will be asked to confirm manually before running them.

Configuration
Stored in:

Linux/macOS: ~/.config/gpt-assistant/

Windows: %APPDATA%\gpt-assistant

Includes:

API key

Execution preferences

Shell config

Usage data

License
MIT License. See LICENSE for more details.

**To run the assistant locally, make sure you have the following installed:
**
Python 3.7 or later
Required to execute the assistant’s scripts.

Check version:

bash
python3 --version

pip (Python package manager)
Required to install dependencies.

Check version:

bash
pip3 --version

Required Python packages
Install all dependencies using pip:

bash
pip install google-generativeai

To run the file, run : 
python assistant.py <prompt> (if u have python instaglled, u can write ur prompt in place of <prompt>)
