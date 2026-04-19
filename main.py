from modules.hardware import get_hardware_info

data = get_hardware_info()
for key, value in data.items():
    print(f"{key.upper()}: {value}")