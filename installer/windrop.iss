; Inno Setup script: builds dist\WinDrop-Setup.exe from dist\WinDrop.exe
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{8F3C2A51-6B7E-4E2D-9C1A-5D4F7B2E9A10}
AppName=WinDrop
AppVersion={#AppVersion}
AppPublisher=WinDrop contributors
DefaultDirName={autopf}\WinDrop
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=WinDrop-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\WinDrop.exe
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\WinDrop.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\WinDrop"; Filename: "{app}\WinDrop.exe"
Name: "{autodesktop}\WinDrop"; Filename: "{app}\WinDrop.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\WinDrop.exe"; Description: "{cm:LaunchProgram,WinDrop}"; Flags: nowait postinstall skipifsilent
