

## Recovering the platform super-admin password

There is no self-service password reset because no verified recovery email or SMS channel is configured. An authorized deployment operator can use the Render service shell and run `python scripts/reset_superadmin_password.py` from the service root. The script prompts for the username and new password with masked input. Do not pass passwords in command arguments or share them in chat.
