; Inno Setup script for ARES Console (built by packaging/windows/build.ps1)
; Installs per-user by default (no admin rights needed) with a private copy of Python.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef Stage
  #define Stage "..\..\build\stage"
#endif

[Setup]
AppId={{FC6AC0E0-4567-4E73-98FF-E8BB614A8410}
AppName=ARES Console
AppVersion={#AppVersion}
AppVerName=ARES Console {#AppVersion}
AppPublisher=ARES Console
AppPublisherURL=https://github.com/scottws70/ARES-Console
AppSupportURL=https://github.com/scottws70/ARES-Console/issues
DefaultDirName={autopf}\ARES Console
DefaultGroupName=ARES Console
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputBaseFilename=ARES-Console-{#AppVersion}-Windows-Setup
SetupIconFile={#Stage}\ares-console.ico
UninstallDisplayIcon={app}\ares-console.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#Stage}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\ARES Console"; Filename: "{app}\python\python.exe"; Parameters: "-m ares_console"; WorkingDir: "{app}"; IconFilename: "{app}\ares-console.ico"; Comment: "Emergency net control console"; Flags: runminimized
Name: "{group}\ARES Console README"; Filename: "{app}\README.md"
Name: "{group}\Uninstall ARES Console"; Filename: "{uninstallexe}"
Name: "{autodesktop}\ARES Console"; Filename: "{app}\python\python.exe"; Parameters: "-m ares_console"; WorkingDir: "{app}"; IconFilename: "{app}\ares-console.ico"; Comment: "Emergency net control console"; Flags: runminimized; Tasks: desktopicon

[Run]
Filename: "{app}\python\python.exe"; Parameters: "-m ares_console"; WorkingDir: "{app}"; Description: "Start ARES Console now"; Flags: postinstall nowait skipifsilent runminimized

[UninstallRun]
; Stop a running copy so its files can be removed. Your logs/settings in %LOCALAPPDATA%\ARES-Console are kept.
Filename: "{app}\python\python.exe"; Parameters: """{app}\stop_ares_console.py"""; Flags: runhidden waituntilterminated; RunOnceId: "StopARES"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\ares_console\__pycache__"
Type: filesandordirs; Name: "{app}\python\__pycache__"
