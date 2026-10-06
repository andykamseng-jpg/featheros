#ifndef AppVersion
  #define AppVersion "0.6.2"
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
OutputBaseFilename=FeatherOS-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=Feather Prep

[Files]
Source: "..\..\dist\FeatherPrep.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dist\FeatherMCP.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dist\README-Windows.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Feather Prep"; Filename: "{app}\FeatherPrep.exe"
Name: "{group}\Uninstall Feather Prep"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\FeatherPrep.exe"; Description: "Launch Feather Prep"; Flags: nowait postinstall skipifsilent
