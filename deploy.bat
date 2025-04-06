@echo off
echo Deploying Telegram Ghibli Bot to GitHub...

git add .
git commit -m "Update bot code"
git push origin master

echo Deployment complete! Railway will automatically detect changes and redeploy.
pause
