# scripts

Helper scripts removed for security - credentials were stored in keyring.

To re-seed:
```python
from proxmox_widget.config.manager import add_or_update_cluster, load_settings
from proxmox_widget.config.models import AuthMode, ClusterConfig
s=load_settings()
c=ClusterConfig(id='pve-192-168-10-2', name='pve-01', host='192.168.10.2', port=8006, verify_ssl=False, auth_mode=AuthMode.PASSWORD, username='root@pam')
add_or_update_cluster(s, c, secret=input('password: '))
```n
