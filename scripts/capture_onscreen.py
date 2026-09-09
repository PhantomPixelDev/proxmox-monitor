import pathlib, sys
sys.path.insert(0, "src")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QScreen
from proxmox_widget.ui.dashboard import Dashboard
from proxmox_widget.config.models import ClusterHealth
import json, pathlib

def load_live():
    p = pathlib.Path("docs/live_health.json")
    if p.exists():
        data = json.loads(p.read_text())
        return [ClusterHealth.model_validate(data)]
    # fallback mock
    from proxmox_widget.config.models import ProxmoxNode, QemuVm, LxcContainer, StorageStatus
    n = ProxmoxNode(node="pve", status="online", cpu=0.38, maxcpu=4, mem=4200000000, maxmem=16650981376, disk=31000000000, maxdisk=100861726720, uptime=14*86400+7*3600)
    vms = [QemuVm(vmid=100,name="parrot-001",node="pve",status="stopped",cpus=4,cpu=0,mem=0,maxmem=8438939648),QemuVm(vmid=112,name="win10",node="pve",status="running",cpus=4,cpu=0.42,mem=2100000000,maxmem=8489271296)]
    cts = [LxcContainer(vmid=107,name="docker",node="pve",status="running",cpus=2,cpu=0.18,mem=690794496,maxmem=4294967296,disk=6195388416,maxdisk=52521566208,uptime=3600)]
    stor=[StorageStatus(storage="local",node="pve",type="dir",status="available",total=100861726720,used=31151751168,avail=69709975552)]
    return [ClusterHealth(cluster_id="pve-192-168-10-2", cluster_name="pve-01", online=True, nodes=[n], vms=vms, containers=cts, storages=stor)]

app = QApplication(sys.argv)
dash = Dashboard()
health = load_live()
dash.update_health(health)
dash.show()
dash.raise_()
dash.activateWindow()
app.processEvents()

def cap():
    screen = app.primaryScreen()
    # grab window with frame via grabWindow
    win_id = int(dash.winId())
    # give window time to paint shadow
    pm = screen.grabWindow(win_id)
    # also try widget grab for comparison
    pm2 = dash.grab()
    out = pathlib.Path("docs/screenshots")
    out.mkdir(parents=True, exist_ok=True)
    # save on-screen window grab as hero
    pm.save(str(out / "dashboard.png"), "PNG")
    pm2.save(str(out / "dashboard-widget.png"), "PNG")
    print(f"saved dashboard {pm.width()}x{pm.height()} to {out/'dashboard.png'}")
    print(f"saved widget {pm2.width()}x{pm2.height()}")
    # also save hero copy as README hero
    # keep only hero, remove fake extra if user wants one
    app.quit()

QTimer.singleShot(900, cap)
sys.exit(app.exec())
