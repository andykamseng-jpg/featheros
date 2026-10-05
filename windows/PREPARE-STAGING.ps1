param(
  [string]$StageRoot,
  [string]$ManifestUrl,
  [string]$ManifestSha256
)
# Download-only preparation for an already existing staging volume.
# No resizing, bootloader changes, Windows removal, or disk erasure occurs here.
$ErrorActionPreference = 'Stop'
function Hash-File([string]$Path) {
  $sha = New-Object System.Security.Cryptography.SHA256Managed
  $stream = [System.IO.File]::OpenRead($Path)
  try { return ([System.BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-','').ToLowerInvariant() }
  finally { $stream.Dispose(); $sha.Dispose() }
}
function Get-HttpsFile([string]$Address, [string]$Destination, [Int64]$Limit) {
  $uri = New-Object System.Uri($Address)
  if ($uri.Scheme -ne 'https' -or $uri.UserInfo) { throw 'Release URLs must be HTTPS without embedded credentials.' }
  $request = [System.Net.HttpWebRequest]::Create($uri)
  $request.AllowAutoRedirect = $false
  $request.Timeout = 30000
  $request.ReadWriteTimeout = 30000
  $response = $request.GetResponse()
  try {
    if ([int]$response.StatusCode -ne 200) { throw 'Release server must return HTTP 200 directly.' }
    $input = $response.GetResponseStream()
    $output = [System.IO.File]::Create($Destination)
    try {
      $buffer = New-Object byte[] 65536
      [Int64]$total = 0
      while (($count = $input.Read($buffer,0,$buffer.Length)) -gt 0) {
        $total += $count
        if ($total -gt $Limit) { throw 'Download exceeds declared size.' }
        $output.Write($buffer,0,$count)
      }
    } finally { $input.Dispose(); $output.Dispose() }
  } finally { $response.Dispose() }
}
if (!$StageRoot -or !$ManifestUrl -or $ManifestSha256 -notmatch '^[a-fA-F0-9]{64}$') {
  throw 'Supply -StageRoot on an existing separate volume, -ManifestUrl and the trusted release -ManifestSha256. No Feather boot release is included in this starter.'
}
$stageFull = [System.IO.Path]::GetFullPath($StageRoot)
$driveRoot = [System.IO.Path]::GetPathRoot($stageFull)
if ($driveRoot.TrimEnd('\') -eq $env:SystemDrive) { throw 'Staging must be on a separate existing volume that will survive Windows replacement.' }
if (!(Test-Path $driveRoot)) { throw 'Staging volume does not exist. This starter does not repartition drives.' }
if (Test-Path $stageFull) { throw 'Use a new staging directory; existing files will not be overwritten.' }
# Windows 7 requires the relevant .NET/TLS updates; lack of TLS is an unsupported host.
try { [System.Net.ServicePointManager]::SecurityProtocol = 3072 } catch { throw 'This Windows/.NET installation cannot request TLS 1.2. Host preparation is unsupported.' }
New-Item -ItemType Directory -Path $stageFull | Out-Null
$manifestPath = Join-Path $stageFull 'release.xml'
Get-HttpsFile $ManifestUrl $manifestPath 1048576
if ((Hash-File $manifestPath) -ne $ManifestSha256.ToLowerInvariant()) { throw 'Manifest hash does not match the trusted release hash.' }
$settings = New-Object System.Xml.XmlReaderSettings
$settings.ProhibitDtd = $true
$settings.XmlResolver = $null
$reader = [System.Xml.XmlReader]::Create($manifestPath,$settings)
$manifest = New-Object System.Xml.XmlDocument
$manifest.XmlResolver = $null
try { $manifest.Load($reader) } finally { $reader.Close() }
if ($manifest.DocumentElement.Name -ne 'feather-release') { throw 'Unexpected release manifest.' }
$files = @($manifest.SelectNodes('/feather-release/file'))
if ($files.Count -lt 1 -or $files.Count -gt 20) { throw 'Manifest needs between 1 and 20 files.' }
[Int64]$required = 104857600
$names = @{}
foreach ($file in $files) {
  if ($file.name -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{0,120}$' -or $file.name -eq 'release.xml' -or $file.name -eq 'STAGING-STATUS.txt' -or $names.ContainsKey($file.name)) { throw 'Invalid or duplicate release filename.' }
  $names[$file.name] = $true
  if ($file.sha256 -notmatch '^[a-fA-F0-9]{64}$' -or $file.size -notmatch '^[0-9]{1,11}$') { throw 'Invalid release checksum or length.' }
  [Int64]$size = $file.size
  if ($size -lt 1 -or $size -gt 10737418240) { throw 'Release file size is outside the supported range.' }
  $required += $size
}
$drive = New-Object System.IO.DriveInfo($driveRoot)
if ($drive.AvailableFreeSpace -lt $required) { throw 'Staging volume has insufficient free space.' }
foreach ($file in $files) {
  $destination = Join-Path $stageFull $file.name
  Get-HttpsFile $file.url $destination ([Int64]$file.size)
  if ((Get-Item $destination).Length -ne [Int64]$file.size -or (Hash-File $destination) -ne $file.sha256.ToLowerInvariant()) { throw ('Release verification failed: ' + $file.name) }
}
@'
Payload files downloaded and verified against the supplied trusted manifest hash.
Boot path configured: NO
Partition resizing implemented: NO
Windows replacement enabled: NO
Next development gate: implement and test the correct firmware/Windows boot adapter.
'@ | Set-Content (Join-Path $stageFull 'STAGING-STATUS.txt')
Write-Host 'Verified payload staged. Windows remains intact. This directory is visible and must survive the eventual Windows-partition replacement.'
