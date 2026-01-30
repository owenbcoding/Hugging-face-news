const path = require('path');
const fs = require('fs');

const venvPython = path.join(__dirname, '.venv', 'bin', 'python');
const interpreter = fs.existsSync(venvPython) ? venvPython : 'python3';

module.exports = {
  apps: [
    {
      name: 'hugging-face-bot',
      script: 'bot.py',
      interpreter,
      cwd: __dirname,
      autorestart: true,
      restart_delay: 5000,
      watch: false,
      env: {
        NODE_ENV: 'production',
      },
    },
  ],
};

