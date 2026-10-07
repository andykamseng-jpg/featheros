#ifndef AppVersion
  #define AppVersion "0.6.8"
#endif

[Setup]
AppId={{09F53C9B-2739-4F41-92E3-4B830BBA71A2}
AppName=Feather Prep
AppVersion={#AppVersion}
AppPublisher=FeatherOS
DefaultDirName={localappdata}\Programs\FeatherOS
DefaultGroupName=FeatherOS
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
OutputDir=..\..\dist
OutputBaseFilename=FeatherOS-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
UninstallDisplayName=Feather Prep

[Files]
Source: "..\..\dist\prep\FeatherPrep\*"; DestDir: "{app}\FeatherPrep"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\dist\mcp\FeatherMCP\*"; DestDir: "{app}\FeatherMCP"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\dist\README-Windows.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Feather Prep"; Filename: "{app}\FeatherPrep\FeatherPrep.exe"
Name: "{group}\Uninstall Feather Prep"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\FeatherPrep\FeatherPrep.exe"; Parameters: "--remove-update-task"; Flags: runhidden waituntilterminated
Filename: "{app}\FeatherPrep\FeatherPrep.exe"; Description: "Launch Feather Prep"; Flags: nowait postinstall skipifsilent
Filename: "{app}\FeatherPrep\FeatherPrep.exe"; Flags: nowait skipifnotsilent

[UninstallRun]
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""FeatherOS Auto Update"" /F"; Flags: runhidden; RunOnceId: "FeatherOSUpdateTask"
