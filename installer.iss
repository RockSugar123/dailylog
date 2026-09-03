[Setup]
AppName=dailylog
AppVersion=1.0.0
AppPublisher=dailylog
DefaultDirName={localappdata}\Programs\dailylog
DefaultGroupName=dailylog
PrivilegesRequired=lowest
Compression=lzma2
SolidCompression=yes
OutputDir=dist
OutputBaseFilename=dailylog-setup-1.0.0
UninstallDisplayIcon={app}\dailylog.exe
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "chinesesimp"; MessagesFile: "installer\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"

[Files]
Source: "..\dailylog-app\*"; DestDir: "{app}"; Excludes: "data,data\*"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\dailylog"; Filename: "{app}\dailylog.exe"
Name: "{group}\卸载 dailylog"; Filename: "{uninstallexe}"
Name: "{commondesktop}\dailylog"; Filename: "{app}\dailylog.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\dailylog.exe"; Description: "立即启动 dailylog"; Flags: nowait postinstall skipifsilent
