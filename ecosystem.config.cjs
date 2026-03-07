const path = require('path');
const fs = require('fs');

// Always use venv Python so dependencies (discord.py, etc.) are available
const appDir = __dirname;
const venvPython = path.join(appDir, '.venv', 'bin', 'python');
const interpreter = fs.existsSync(venvPython) ? venvPython : 'python3';

module.exports = {
  apps: [
    {
      name: 'hugging-face-bot',
      script: path.join(appDir, 'bot.py'),
      interpreter,
      cwd: appDir,
      autorestart: true,
      restart_delay: 5000,
      watch: false,
      env: {
        NODE_ENV: 'production',
      },
    },
  ],
};

