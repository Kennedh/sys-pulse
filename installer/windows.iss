#ifndef AppVersion
#define AppVersion "3.1.0"
#endif
#ifndef ProjectRoot
#define ProjectRoot ".."
#endif
[Setup]
AppId={{5385F142-031A-4928-9569-760BA8FC6783}
AppName=SysPulse
AppVersion={#AppVersion}
AppPublisher=Kennedh
AppPublisherURL=https://github.com/Kennedh/sys-pulse
AppSupportURL=https://github.com/Kennedh/sys-pulse/issues
AppUpdatesURL=https://github.com/Kennedh/sys-pulse/releases
DefaultDirName={localappdata}\Programs\SysPulse
DefaultGroupName=SysPulse
DisableDirPage=no
DisableProgramGroupPage=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#ProjectRoot}\dist\releases
OutputBaseFilename=SysPulse-{#AppVersion}-Windows-x64-Setup
SetupIconFile={#ProjectRoot}\assets\syspulse.ico
UninstallDisplayIcon={app}\SysPulse.exe
LicenseFile={#ProjectRoot}\LICENSE
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked
Name: "integrated"; Description: "Usar análise integrada, sem download de modelo"; GroupDescription: "Análise inicial:"; Flags: exclusive
Name: "localai"; Description: "Preparar IA local e escolher o modelo após instalar (download separado)"; GroupDescription: "Análise inicial:"; Flags: exclusive unchecked
Name: "onlineai"; Description: "Configurar IA anônima na nuvem, sem login ou chave (fila comunitária)"; GroupDescription: "Análise inicial:"; Flags: exclusive unchecked
[Files]
Source: "{#ProjectRoot}\dist\SysPulse\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\SysPulse"; Filename: "{app}\SysPulse.exe"
Name: "{group}\Desinstalar SysPulse"; Filename: "{uninstallexe}"
Name: "{group}\Downloads e atualizações"; Filename: "https://github.com/Kennedh/sys-pulse/releases"
Name: "{autodesktop}\SysPulse"; Filename: "{app}\SysPulse.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\SysPulse.exe"; Parameters: "{code:StartupArguments}"; Description: "Abrir SysPulse e concluir a configuração"; Flags: nowait postinstall skipifsilent
[Code]
function StartupArguments(Param: String): String;
begin
  Result := '';
  if WizardIsTaskSelected('localai') then Result := '--setup-local';
  if WizardIsTaskSelected('onlineai') then Result := '--setup-online';
end;
