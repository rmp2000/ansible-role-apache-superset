import json, re, subprocess, sys
from pathlib import Path
from urllib.parse import quote
settings=json.loads(Path('/etc/apache-superset/settings.json').read_text())
mode=sys.argv[1]
command=['/opt/apache-superset/bin/superset','db','upgrade'] if mode=='migrate' else ['/opt/apache-superset/bin/python','/usr/local/bin/apache-superset-provision']
result=subprocess.run(command,capture_output=True,text=True)
text=result.stdout+'\\n'+result.stderr
for value in settings.values():
    if isinstance(value,str) and len(value)>=16:
        text=text.replace(value,'<redacted>').replace(quote(value,safe=''),'<redacted>')
text=re.sub(r'eyJ[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+','<JWT redacted>',text)
if result.returncode:
    print(text[-14000:]);sys.exit(result.returncode)
print(('SCHEMA_CHANGED' if 'Running upgrade' in text else 'SCHEMA_OK') if mode=='migrate' else ('SUPERSET_PROVISION_CHANGED' if 'SUPERSET_PROVISION_CHANGED' in text else 'SUPERSET_PROVISION_OK'))
