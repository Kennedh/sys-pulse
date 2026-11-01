from pathlib import Path
import xml.etree.ElementTree as ET


def write_profile(destination, memory_mib=128):
    memory_mib = max(32, min(512, int(memory_mib)))
    root = ET.Element("WindowsPerformanceRecorder", Version="1.0", Author="SysPulse")
    profiles = ET.SubElement(root, "Profiles")
    collector = ET.SubElement(profiles, "SystemCollector", Id="SysPulseCollector", Name="SysPulse kernel")
    ET.SubElement(collector, "BufferSize", Value="1024")
    ET.SubElement(collector, "Buffers", Value=str(memory_mib))
    provider = ET.SubElement(profiles, "SystemProvider", Id="SysPulseProvider")
    keywords = ET.SubElement(provider, "Keywords")
    for name in ("ProcessThread", "Loader", "SampledProfile", "CSwitch", "DiskIO", "DiskIOInit",
                 "DPC", "Interrupt", "HardFaults"):
        ET.SubElement(keywords, "Keyword", Value=name)
    for mode in ("Memory", "File"):
        profile = ET.SubElement(profiles, "Profile", Id=f"SysPulse.Light.{mode}", Name="SysPulse",
                                Description="CPU, disco, memoria e drivers", LoggingMode=mode, DetailLevel="Light")
        collectors = ET.SubElement(profile, "Collectors")
        identifier = ET.SubElement(collectors, "SystemCollectorId", Value="SysPulseCollector")
        ET.SubElement(identifier, "SystemProviderId", Value="SysPulseProvider")
    path = Path(destination)
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path
