#!/usr/bin/env python3
"""
GPT Assistant - Terminal-based AI command generator
A cross-platform tool that uses Gemini AI to generate and execute shell commands
"""

import os
import sys
import json
import subprocess
import platform
import shutil
import re
import argparse
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import tempfile

try:
    import google.generativeai as genai
except ImportError:
    print("Error: google-generativeai package not found.")
    print("Install it with: pip install google-generativeai")
    sys.exit(1)

class RateLimiter:
    """Simple rate limiter for API calls"""
    def __init__(self, max_calls: int = 60, window_minutes: int = 1):
        self.max_calls = max_calls
        self.window_minutes = window_minutes
        self.calls = []
    
    def can_make_call(self) -> bool:
        """Check if we can make another API call"""
        now = datetime.now()
        # Remove old calls outside the window
        cutoff = now - timedelta(minutes=self.window_minutes)
        self.calls = [call_time for call_time in self.calls if call_time > cutoff]
        
        return len(self.calls) < self.max_calls
    
    def record_call(self):
        """Record that we made an API call"""
        self.calls.append(datetime.now())
    
    def time_until_next_call(self) -> int:
        """Get seconds until next call is allowed"""
        if self.can_make_call():
            return 0
        
        # Find the oldest call that will expire next
        oldest_call = min(self.calls)
        next_available = oldest_call + timedelta(minutes=self.window_minutes)
        return int((next_available - datetime.now()).total_seconds())

class GPTAssistant:
    def __init__(self):
        self.system_info = self._get_system_info()
        self.config_dir = self._get_config_dir()
        self.config_file = self.config_dir / "gpt-assistant-config.json"
        self.usage_file = self.config_dir / "usage.json"
        self.config = self._load_config()
        self.gemini_model = None
        
        # Initialize rate limiter (60 calls per minute by default)
        self.rate_limiter = RateLimiter(
            max_calls=self.config.get('rate_limit_calls', 60),
            window_minutes=self.config.get('rate_limit_window', 1)
        )
        
        # Load usage tracking
        self.usage = self._load_usage()
        
        # Safety filters - commands that should never auto-execute
        self.dangerous_commands = [
            'rm -rf', 'del /f', 'format', 'fdisk', 'mkfs', 'dd if=', 'shutdown',
            'reboot', 'halt', 'poweroff', 'init 0', 'init 6', 'systemctl poweroff',
            'systemctl reboot', 'chmod 777', 'chown root', 'sudo rm', 'sudo dd',
            'curl.*|.*sh', 'wget.*|.*sh', ':(){ :|:& };:', 'sudo chmod -R 777',
            'sudo chown -R', 'rm -r /', 'del C:\\', 'rmdir /s', 'takeown /f',
            'icacls.*grant.*full', 'net user.*add', 'useradd', 'userdel',
            'passwd', 'su -', 'sudo su', 'pkill -9', 'killall -9'
        ]
        
        # Command patterns that need confirmation
        self.risky_commands = [
            r'sudo\s+', r'rm\s+', r'del\s+', r'move\s+', r'mv\s+',
            r'cp\s+.*\s+/', r'copy\s+.*\s+\\', r'chmod\s+', r'chown\s+',
            r'git\s+reset\s+--hard', r'git\s+clean\s+-fd', r'npm\s+install\s+-g',
            r'pip\s+install\s+', r'apt\s+install', r'yum\s+install',
            r'systemctl\s+', r'service\s+', r'crontab\s+', r'mount\s+',
            r'umount\s+', r'fdisk\s+', r'parted\s+'
        ]

    def _get_system_info(self) -> Dict:
        """Collect system information for AI context"""
        info = {
            'os': platform.system(),
            'os_version': platform.version(),
            'architecture': platform.machine(),
            'python_version': platform.python_version(),
            'shell': os.environ.get('SHELL', 'unknown'),
            'terminal': os.environ.get('TERM', 'unknown'),
            'user': os.environ.get('USER', os.environ.get('USERNAME', 'unknown')),
            'home': str(Path.home()),
            'cwd': os.getcwd(),
            'path_separator': os.pathsep,
            'available_tools': []
        }
        
        # Check for common tools
        tools_to_check = ['git', 'docker', 'npm', 'pip', 'curl', 'wget', 'grep', 'find']
        for tool in tools_to_check:
            if shutil.which(tool):
                info['available_tools'].append(tool)
        
        return info

    def _get_config_dir(self) -> Path:
        """Get configuration directory path"""
        if platform.system() == 'Windows':
            config_dir = Path(os.environ.get('APPDATA', Path.home())) / 'gpt-assistant'
        else:
            config_dir = Path.home() / '.config' / 'gpt-assistant'
        
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir

    def _load_config(self) -> Dict:
        """Load configuration from file"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save_config(self):
        """Save configuration to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
        except IOError as e:
            print(f"Error saving config: {e}")

    def _load_usage(self) -> Dict:
        """Load usage tracking data"""
        if self.usage_file.exists():
            try:
                with open(self.usage_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {'total_calls': 0, 'daily_usage': {}}

    def _save_usage(self):
        """Save usage tracking data"""
        try:
            with open(self.usage_file, 'w') as f:
                json.dump(self.usage, f, indent=2)
        except IOError as e:
            print(f"Error saving usage: {e}")

    def _record_api_call(self):
        """Record an API call for usage tracking"""
        self.usage['total_calls'] = self.usage.get('total_calls', 0) + 1
        
        today = datetime.now().strftime('%Y-%m-%d')
        daily = self.usage.get('daily_usage', {})
        daily[today] = daily.get(today, 0) + 1
        self.usage['daily_usage'] = daily
        
        # Keep only last 30 days of data
        cutoff = datetime.now() - timedelta(days=30)
        self.usage['daily_usage'] = {
            date: count for date, count in daily.items()
            if datetime.strptime(date, '%Y-%m-%d') > cutoff
        }
        
        self._save_usage()

    def _get_api_key_securely(self) -> str:
        """Get API key with better security practices"""
        print("🔑 Gemini API Key Setup")
        print("=" * 50)
        print("You need a Gemini API key to use this assistant.")
        print("Get one free at: https://makersuite.google.com/app/apikey")
        print("")
        print("🔒 Security Notes:")
        print("• Your API key is stored locally on your computer")
        print("• Never share your API key with others")
        print("• You can revoke/regenerate keys in Google AI Studio")
        print("• This tool makes API calls on your behalf")
        print("")
        
        # Try to get from environment variable first
        api_key = os.environ.get('GEMINI_API_KEY')
        if api_key:
            print("✅ Found API key in GEMINI_API_KEY environment variable")
            return api_key
        
        # Interactive input
        try:
            import getpass
            api_key = getpass.getpass("Enter your Gemini API key (input hidden): ").strip()
        except Exception:
            api_key = input("Enter your Gemini API key: ").strip()
        
        if not api_key:
            print("❌ API key is required to use the assistant.")
            return None
        
        # Validate key format (basic check)
        if not api_key.startswith('AI') or len(api_key) < 20:
            print("⚠️  Warning: This doesn't look like a valid Gemini API key")
            confirm = input("Continue anyway? (y/n): ").strip().lower()
            if confirm != 'y':
                return None
        
        return api_key

    def _setup_gemini(self) -> bool:
        """Setup Gemini AI with API key"""
        api_key = self.config.get('gemini_api_key')
        
        if not api_key:
            api_key = self._get_api_key_securely()
            if not api_key:
                return False
            
            # Ask if user wants to save the key
            save_key = input("Save API key for future use? (y/n) [y]: ").strip().lower()
            if save_key != 'n':
                self.config['gemini_api_key'] = api_key
                self._save_config()
                print("✅ API key saved")
            else:
                print("ℹ️  API key not saved - you'll need to enter it each time")
        
        try:
            genai.configure(api_key=api_key)
            # Try the newer model names first, fall back to older ones
            model_names = ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']
            
            for model_name in model_names:
                try:
                    self.gemini_model = genai.GenerativeModel(model_name)
                    # Test the connection
                    if not self.rate_limiter.can_make_call():
                        print(f"⏳ Rate limit reached. Wait {self.rate_limiter.time_until_next_call()} seconds")
                        return False
                    
                    self.rate_limiter.record_call()
                    response = self.gemini_model.generate_content("Hello, respond with just 'OK'")
                    self._record_api_call()
                    
                    if response.text and 'OK' in response.text:
                        print(f"✅ Connected using model: {model_name}")
                        return True
                except Exception as e:
                    print(f"⚠️ Model {model_name} not available: {e}")
                    continue
            
            raise Exception("No available models found")
        except Exception as e:
            print(f"❌ Error setting up Gemini: {e}")
            print("Please check your API key and internet connection.")
            # Remove invalid key
            if 'gemini_api_key' in self.config:
                del self.config['gemini_api_key']
                self._save_config()
            return False

    def _first_run_setup(self):
        """Run initial setup questions"""
        print("🚀 Welcome to GPT Assistant!")
        print("Let's set up your assistant with a few questions...\n")
        
        # Auto-run permission
        auto_run = input("Allow auto-execution of safe commands? (y/n) [y]: ").strip().lower()
        self.config['auto_run'] = auto_run != 'n'
        
        # Confirmation for risky commands
        confirm_risky = input("Always confirm risky commands? (y/n) [y]: ").strip().lower()
        self.config['confirm_risky'] = confirm_risky != 'n'
        
        # Rate limiting setup
        print("\n📊 Rate Limiting Setup")
        print("This prevents accidentally making too many API calls.")
        rate_limit = input("Max API calls per minute (10-120) [60]: ").strip()
        try:
            rate_limit = int(rate_limit) if rate_limit else 60
            rate_limit = max(10, min(120, rate_limit))  # Clamp between 10-120
            self.config['rate_limit_calls'] = rate_limit
        except ValueError:
            self.config['rate_limit_calls'] = 60
        
        # Terminal preferences
        print(f"\nDetected terminal: {self.system_info['terminal']}")
        print(f"Detected shell: {self.system_info['shell']}")
        custom_shell = input("Use different shell? (leave empty for default): ").strip()
        if custom_shell:
            self.config['preferred_shell'] = custom_shell
        
        # Save system info
        self.config['system_info'] = self.system_info
        self.config['first_run_complete'] = True
        
        self._save_config()
        print("\n✅ Setup complete! You can now use the assistant.")

    def _is_dangerous_command(self, command: str) -> bool:
        """Check if command is dangerous"""
        command_lower = command.lower()
        for dangerous in self.dangerous_commands:
            if dangerous in command_lower:
                return True
        return False

    def _is_risky_command(self, command: str) -> bool:
        """Check if command is risky and needs confirmation"""
        for pattern in self.risky_commands:
            if re.search(pattern, command, re.IGNORECASE):
                return True
        return False

    def _get_command_prompt(self, user_request: str) -> str:
        """Generate prompt for AI command generation"""
        system_context = f"""
System Information:
- OS: {self.system_info['os']} {self.system_info['os_version']}
- Architecture: {self.system_info['architecture']}
- Shell: {self.system_info['shell']}
- Terminal: {self.system_info['terminal']}
- Available tools: {', '.join(self.system_info['available_tools'])}
- Current directory: {os.getcwd()}

User Request: {user_request}

Generate ONLY the shell command(s) needed to fulfill this request. Rules:
1. Return only the command, no explanations
2. Use commands appropriate for {self.system_info['os']}
3. Assume the user is in their current directory: {os.getcwd()}
4. If multiple commands are needed, separate them with ' && '
5. Use safe, standard commands when possible
6. Don't use sudo unless absolutely necessary
7. For file operations, use relative paths when possible

Command:"""
        
        return system_context

    def _generate_command(self, user_request: str) -> Optional[str]:
        """Generate command using Gemini AI"""
        if not self.gemini_model:
            if not self._setup_gemini():
                return None
        
        # Check rate limit
        if not self.rate_limiter.can_make_call():
            wait_time = self.rate_limiter.time_until_next_call()
            print(f"⏳ Rate limit reached. Please wait {wait_time} seconds before making another request.")
            return None
        
        try:
            prompt = self._get_command_prompt(user_request)
            self.rate_limiter.record_call()
            response = self.gemini_model.generate_content(prompt)
            self._record_api_call()
            
            if not response.text:
                return None
                
            # Extract command from response
            command = response.text.strip()
            
            # Remove common AI response prefixes
            prefixes_to_remove = ['```bash', '```sh', '```', '$', '> ', 'Command:', 'command:']
            for prefix in prefixes_to_remove:
                if command.startswith(prefix):
                    command = command[len(prefix):].strip()
            
            # Remove trailing ```
            if command.endswith('```'):
                command = command[:-3].strip()
            
            return command
            
        except Exception as e:
            print(f"❌ Error generating command: {e}")
            return None

    def _execute_command(self, command: str) -> Tuple[bool, str, str]:
        """Execute command and return success status, stdout, stderr"""
        try:
            # Use the preferred shell if configured
            shell = self.config.get('preferred_shell', True)
            
            if platform.system() == 'Windows':
                result = subprocess.run(
                    command, shell=shell, capture_output=True, text=True, timeout=30
                )
            else:
                result = subprocess.run(
                    command, shell=shell, capture_output=True, text=True, timeout=30
                )
            
            return (result.returncode == 0, result.stdout, result.stderr)
            
        except subprocess.TimeoutExpired:
            return (False, "", "Command timed out after 30 seconds")
        except Exception as e:
            return (False, "", str(e))

    def _attempt_fix_command(self, original_command: str, error: str) -> Optional[str]:
        """Try to fix a failed command using AI"""
        if not self.gemini_model:
            return None
        
        # Check rate limit
        if not self.rate_limiter.can_make_call():
            print(f"⏳ Cannot fix command: Rate limit reached")
            return None
            
        try:
            fix_prompt = f"""
The following command failed:
Command: {original_command}
Error: {error}

System: {self.system_info['os']}
Current directory: {os.getcwd()}

Generate a corrected version of this command that should work. Return only the fixed command, no explanations.

Fixed command:"""
            
            self.rate_limiter.record_call()
            response = self.gemini_model.generate_content(fix_prompt)
            self._record_api_call()
            
            if response.text:
                return response.text.strip()
                
        except Exception:
            pass
            
        return None

    def handle_gpt_command(self, user_request: str):
        """Handle a GPT command request"""
        if not self.config.get('first_run_complete'):
            self._first_run_setup()
        
        print(f"🤖 Generating command for: {user_request}")
        
        # Generate command
        command = self._generate_command(user_request)
        if not command:
            print("❌ Failed to generate command")
            return
        
        print(f"📝 Generated command: {command}")
        
        # Safety checks
        if self._is_dangerous_command(command):
            print("⚠️  Command blocked: Potentially dangerous operation detected")
            print("🔒 For safety, this command will not be executed automatically")
            confirm = input("Are you sure you want to run this command? (type 'yes' to confirm): ")
            if confirm.lower() != 'yes':
                print("Command cancelled")
                return
        
        # Risk assessment
        elif self._is_risky_command(command) and self.config.get('confirm_risky', True):
            print("⚠️  Risky command detected - requires confirmation")
            confirm = input("Execute this command? (y/n): ").strip().lower()
            if confirm != 'y':
                print("Command cancelled")
                return
        
        # Auto-run check
        elif not self.config.get('auto_run', False):
            confirm = input("Execute this command? (y/n): ").strip().lower()
            if confirm != 'y':
                print("Command cancelled")
                return
        
        # Execute command
        print("🚀 Executing command...")
        success, stdout, stderr = self._execute_command(command)
        
        if success:
            print("✅ Command executed successfully!")
            if stdout:
                print(f"Output:\n{stdout}")
        else:
            print(f"❌ Command failed: {stderr}")
            
            # Attempt to fix and retry
            if self.config.get('auto_fix', True):
                print("🔧 Attempting to fix command...")
                fixed_command = self._attempt_fix_command(command, stderr)
                
                if fixed_command and fixed_command != command:
                    print(f"🔄 Suggested fix: {fixed_command}")
                    retry = input("Try the fixed command? (y/n): ").strip().lower()
                    
                    if retry == 'y':
                        print("🚀 Executing fixed command...")
                        success, stdout, stderr = self._execute_command(fixed_command)
                        
                        if success:
                            print("✅ Fixed command executed successfully!")
                            if stdout:
                                print(f"Output:\n{stdout}")
                        else:
                            print(f"❌ Fixed command also failed: {stderr}")

    def usage_stats(self):
        """Show usage statistics"""
        print("📊 Usage Statistics")
        print("=" * 30)
        print(f"Total API calls: {self.usage.get('total_calls', 0)}")
        print(f"Rate limit: {self.config.get('rate_limit_calls', 60)} calls/minute")
        
        # Show recent daily usage
        daily = self.usage.get('daily_usage', {})
        if daily:
            print("\nRecent usage:")
            for date in sorted(daily.keys())[-7:]:  # Last 7 days
                print(f"  {date}: {daily[date]} calls")
        
        # Rate limiter status
        if self.rate_limiter.can_make_call():
            print(f"\n✅ Ready to make API calls")
        else:
            wait_time = self.rate_limiter.time_until_next_call()
            print(f"\n⏳ Rate limited - wait {wait_time} seconds")

    def manage_api_key(self):
        """Manage API key"""
        print("🔑 API Key Management")
        print("=" * 30)
        
        has_key = 'gemini_api_key' in self.config
        env_key = bool(os.environ.get('GEMINI_API_KEY'))
        
        print(f"Saved API key: {'✅' if has_key else '❌'}")
        print(f"Environment variable: {'✅' if env_key else '❌'}")
        
        if has_key:
            print("\nOptions:")
            print("1. Remove saved API key")
            print("2. Replace API key")
            print("3. Cancel")
            
            choice = input("Choose option (1-3): ").strip()
            
            if choice == '1':
                del self.config['gemini_api_key']
                self._save_config()
                print("✅ API key removed")
            elif choice == '2':
                new_key = self._get_api_key_securely()
                if new_key:
                    self.config['gemini_api_key'] = new_key
                    self._save_config()
                    print("✅ API key updated")
        else:
            print("\nNo API key saved. Set one up:")
            api_key = self._get_api_key_securely()
            if api_key:
                save_key = input("Save this API key? (y/n): ").strip().lower()
                if save_key == 'y':
                    self.config['gemini_api_key'] = api_key
                    self._save_config()
                    print("✅ API key saved")

    def enable(self):
        """Enable the assistant"""
        self.config['enabled'] = True
        self._save_config()
        print("✅ GPT Assistant enabled")

    def disable(self):
        """Disable the assistant"""
        self.config['enabled'] = False
        self._save_config()
        print("❌ GPT Assistant disabled")

    def status(self):
        """Show assistant status"""
        enabled = self.config.get('enabled', True)
        first_run = self.config.get('first_run_complete', False)
        has_key = 'gemini_api_key' in self.config or bool(os.environ.get('GEMINI_API_KEY'))
        
        print(f"GPT Assistant Status:")
        print(f"  Enabled: {'✅' if enabled else '❌'}")
        print(f"  Configured: {'✅' if first_run else '❌'}")
        print(f"  API Key: {'✅' if has_key else '❌'}")
        print(f"  Auto-run: {'✅' if self.config.get('auto_run', False) else '❌'}")
        print(f"  Confirm risky: {'✅' if self.config.get('confirm_risky', True) else '❌'}")
        print(f"  Rate limit: {self.config.get('rate_limit_calls', 60)} calls/minute")
        print(f"  System: {self.system_info['os']}")
        print(f"  Config: {self.config_file}")

    def reset(self):
        """Reset configuration"""
        print("🔄 Reset Configuration")
        print("This will remove all settings and usage data.")
        print("Your API key will also be removed (if saved).")
        
        confirm = input("Are you sure you want to reset everything? (type 'yes' to confirm): ").strip().lower()
        if confirm == 'yes':
            if self.config_file.exists():
                self.config_file.unlink()
            if self.usage_file.exists():
                self.usage_file.unlink()
            print("✅ Configuration and usage data reset")
        else:
            print("Reset cancelled")

def main():
    assistant = GPTAssistant()
    
    # Check for management flags first
    if len(sys.argv) > 1:
        if sys.argv[1] == '--enable':
            assistant.enable()
            return
        elif sys.argv[1] == '--disable':
            assistant.disable()
            return
        elif sys.argv[1] == '--status':
            assistant.status()
            return
        elif sys.argv[1] == '--reset':
            assistant.reset()
            return
        elif sys.argv[1] == '--usage':
            assistant.usage_stats()
            return
        elif sys.argv[1] == '--api-key':
            assistant.manage_api_key()
            return
        elif sys.argv[1] in ['-h', '--help']:
            print("GPT Assistant - AI-powered command generator")
            print("\nUsage: python gpt-assistant.py <your request>")
            print("Example: python gpt-assistant.py find all python files in current directory")
            print("\nManagement commands:")
            print("  --enable     Enable the assistant")
            print("  --disable    Disable the assistant")
            print("  --status     Show assistant status")
            print("  --usage      Show usage statistics")
            print("  --api-key    Manage API key")
            print("  --reset      Reset all configuration")
            print("  --help       Show this help message")
            print("\nAPI Key Setup:")
            print("  Get a free API key at: https://makersuite.google.com/app/apikey")
            print("  Set via environment variable: export GEMINI_API_KEY=your_key")
            print("  Or let the assistant prompt you on first use")
            return
    
    # Check if assistant is enabled
    if not assistant.config.get('enabled', True):
        print("GPT Assistant is disabled. Use '--enable' to enable it.")
        return
    
    # Handle GPT command
    if len(sys.argv) > 1:
        user_request = ' '.join(sys.argv[1:])
        assistant.handle_gpt_command(user_request)
    else:
        print("Usage: python gpt-assistant.py <your request>")
        print("Example: python gpt-assistant.py find all python files in current directory")
        print("Use --help for more options")

if __name__ == "__main__":
    main()
