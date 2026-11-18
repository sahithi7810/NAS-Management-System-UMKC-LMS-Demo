import psutil
import time
import platform
previous_network = None
previous_network_time = None

def get_system_info():
    global previous_network, previous_network_time

    cpu_usage = psutil.cpu_percent(interval=1)

    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    network = psutil.net_io_counters()
    current_time = time.time()
    if previous_network is None or previous_network_time is None:
        upload_speed = 0.0
        download_speed = 0.0
    else:
        elapsed = max(current_time - previous_network_time, 0.001)
        upload_speed = max(
            0, network.bytes_sent - previous_network.bytes_sent
        ) / 1024 / elapsed
        download_speed = max(
            0, network.bytes_recv - previous_network.bytes_recv
        ) / 1024 / elapsed
    previous_network = network
    previous_network_time = current_time
 
    uptime_seconds = time.time() - psutil.boot_time()
    uptime_hours = round(uptime_seconds / 3600, 2)

    return {
        "cpu": cpu_usage,
        "ram": memory.percent,
        "ram_total": round(memory.total / (1024 ** 3), 2),
        "ram_used": round(memory.used / (1024 ** 3), 2),
        "disk": disk.percent,
        "disk_total": round(disk.total / (1024 ** 3), 2),
        "disk_used": round(disk.used / (1024 ** 3), 2),
        "disk_free": round(disk.free / (1024 ** 3), 2),
        "network_sent": round(network.bytes_sent / (1024 ** 2), 2),
        "network_received": round(network.bytes_recv / (1024 ** 2), 2),
        "upload_speed": round(upload_speed, 2),
        "download_speed": round(download_speed, 2),
        "uptime": uptime_hours,
        "os": platform.system()
    }



