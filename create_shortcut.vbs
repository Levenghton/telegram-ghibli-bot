Set WshShell = CreateObject("WScript.Shell")
StartupFolder = WshShell.SpecialFolders("Startup")
Set shortcut = WshShell.CreateShortcut(StartupFolder & "\TelegramGhibliBot.lnk")
shortcut.TargetPath = "C:\Users\Admin\Desktop\telegram-ghibli-bot\autostart_bot.bat"
shortcut.WorkingDirectory = "C:\Users\Admin\Desktop\telegram-ghibli-bot"
shortcut.IconLocation = "C:\Windows\System32\SHELL32.dll,21"
shortcut.Save
