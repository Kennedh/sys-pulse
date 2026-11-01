[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$result = @{}
function Read-Section($name, [scriptblock]$query) {
    try { $result[$name] = @{status='ok'; rows=@(& $query)} }
    catch { $result[$name] = @{status='erro'; rows=@(); error=$_.Exception.Message} }
}
Read-Section 'devices' {
    Get-CimInstance Win32_PnPEntity | Select-Object DeviceID, Name, PNPClass, Present, ConfigManagerErrorCode
}
Read-Section 'drivers' {
    Get-CimInstance Win32_PnPSignedDriver | Select-Object DeviceID, DeviceName, DeviceClass,
        DriverProviderName, DriverVersion, @{n='DriverDate';e={if ($_.DriverDate -is [datetime]) {$_.DriverDate.ToString('yyyy-MM-dd')} else {[string]$_.DriverDate}}}, IsSigned, InfName
}
Read-Section 'storage' {
    foreach ($disk in Get-PhysicalDisk) {
        $row = @{DeviceId=$disk.DeviceId; FriendlyName=$disk.FriendlyName; MediaType=[string]$disk.MediaType;
            HealthStatus=[string]$disk.HealthStatus; OperationalStatus=($disk.OperationalStatus -join ', ');
            Size=$disk.Size; Reliability=$null; ReliabilityError=$null}
        try {
            $row.Reliability = $disk | Get-StorageReliabilityCounter | Select-Object Temperature, Wear,
                PowerOnHours, ReadErrorsUncorrected, WriteErrorsUncorrected
        } catch { $row.ReliabilityError = $_.Exception.Message }
        $row
    }
}
Read-Section 'events' {
    $providers = 'Microsoft-Windows-WHEA-Logger','Microsoft-Windows-Kernel-Power','disk','Ntfs','stornvme','storahci','Display','Microsoft-Windows-WER-SystemErrorReporting'
    $providerFilter = ($providers | ForEach-Object {"Provider[@Name='$_']"}) -join ' or '
    $filter = "*[System[($providerFilter) and (Level=1 or Level=2 or Level=3) and TimeCreated[timediff(@SystemTime) <= 86400000]]]"
    try {
        Get-WinEvent -LogName System -FilterXPath $filter -MaxEvents 100 |
            Select-Object @{n='TimeCreated';e={$_.TimeCreated.ToString('o')}}, ProviderName, Id, Level,
                @{n='Message';e={if ($_.Message) {$_.Message.Substring(0, [Math]::Min(2000, $_.Message.Length))}}}
    } catch {
        if ($_.FullyQualifiedErrorId -notlike 'NoMatchingEventsFound*') { throw }
    }
}
ConvertTo-Json -InputObject $result -Depth 6 -Compress
