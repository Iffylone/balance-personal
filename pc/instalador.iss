[Setup]
AppName=Balance personal
AppVersion=2026.10
AppPublisher=Iffyware Systems
DefaultDirName={localappdata}\SistContiffy
PrivilegesRequired=lowest
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
OutputDir=salida
OutputBaseFilename=Instalar_Balance_personal
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\SistContiffy.exe
Compression=lzma2
SolidCompression=yes
[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
[Files]
Source: "dist\SistContiffy.exe"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{userdesktop}\Balance personal"; Filename: "{app}\SistContiffy.exe"
Name: "{userprograms}\Balance personal"; Filename: "{app}\SistContiffy.exe"
[Run]
Filename: "{app}\SistContiffy.exe"; Description: "Abrir Balance personal"; Flags: nowait postinstall skipifsilent
