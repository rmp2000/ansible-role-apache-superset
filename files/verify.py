"""Authenticated API, persistent metadata and isolated backup restoration checks."""
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid
import requests
SETTINGS=json.loads(Path('/etc/apache-superset/settings.json').read_text())
ROOT=Path(SETTINGS['data_dir'])
STATE=ROOT/'.verification.json'
URL='https://127.0.0.1:8088'
CA='/etc/apache-superset/tls/server.crt'
def session():
    s=requests.Session();s.verify=CA;s.headers['Referer']=URL+'/'
    r=s.post(URL+'/api/v1/security/login',json={'username':'admin','password':SETTINGS['admin_password'],'provider':'db','refresh':True},timeout=30)
    r.raise_for_status();s.headers['Authorization']='Bearer '+r.json()['access_token']
    r=s.get(URL+'/api/v1/security/csrf_token/',timeout=30);r.raise_for_status();s.headers['X-CSRFToken']=r.json()['result']
    return s
def request(s,method,path,**kw):
    r=s.request(method,URL+path,timeout=90,**kw);r.raise_for_status();return r
def wait():
    end=time.monotonic()+180
    while time.monotonic()<end:
        try:return session()
        except Exception:time.sleep(2)
    raise RuntimeError('Authenticated Superset readiness timed out')
def stage(s):
    if STATE.exists():raise RuntimeError('A previous metadata fixture is pending')
    title='verification-'+uuid.uuid4().hex
    value=request(s,'POST','/api/v1/dashboard/',json={'dashboard_title':title,'published':False}).json()
    STATE.write_text(json.dumps({'id':value['id'],'title':title}));STATE.chmod(0o600)
    print('SUPERSET_DURABLE_DASHBOARD_STAGED')
def check(s):
    value=json.loads(STATE.read_text())
    dashboard=request(s,'GET','/api/v1/dashboard/'+str(value['id'])).json()['result']
    if dashboard['dashboard_title']!=value['title']:raise RuntimeError('Dashboard metadata changed')
    request(s,'DELETE','/api/v1/dashboard/'+str(value['id']))
    STATE.unlink();print('SUPERSET_PERSISTENCE_OK')
def pg(*args):
    return subprocess.run(['runuser','-u','postgres','--',*args],check=True,capture_output=True,text=True).stdout
def main():
    mode=sys.argv[1];s=wait()
    if mode=='stage':stage(s);return
    if mode=='check':check(s);return
    if mode=='restart':
        stage(s);subprocess.run(['systemctl','restart','apache-superset'],check=True,capture_output=True);check(wait());return
    if mode=='backup':
        stage(s)
        fixture=json.loads(STATE.read_text());name='superset_restore_'+uuid.uuid4().hex
        archive=ROOT/'backups'/('metadata-'+uuid.uuid4().hex+'.dump')
        pg('pg_dump','-p','5433','-Fc','-f',str(archive),'superset')
        try:
            pg('createdb','-p','5433',name)
            pg('pg_restore','-p','5433','--exit-on-error','-d',name,str(archive))
            found=pg('psql','-p','5433','-d',name,'-Atc','SELECT dashboard_title FROM dashboards WHERE id='+str(int(fixture['id']))).strip()
            if found!=fixture['title']:raise RuntimeError('Restored metadata fixture differs')
        finally:
            pg('dropdb','-p','5433','--if-exists',name);check(s)
        protected=archive.with_suffix('.settings.json');protected.write_text(json.dumps(SETTINGS));protected.chmod(0o600)
        print('SUPERSET_BACKUP_RESTORE_OK');return
    if mode!='smoke':raise RuntimeError('Unknown verification mode')
    request(s,'GET','/api/v1/me/')
    bad=requests.post(URL+'/api/v1/security/login',json={'username':'admin','password':'invalid-password','provider':'db'},timeout=20,verify=CA)
    if bad.status_code<400:raise RuntimeError('Invalid administrator password accepted')
    unauth=requests.get(URL+'/api/v1/dashboard/',timeout=20,verify=CA)
    if unauth.status_code<400:raise RuntimeError('Dashboard API accepted anonymous access')
    if SETTINGS['analytics_enabled']:
        r=request(s,'GET','/api/v1/dataset/').json()
        datasets=[v for v in r['result'] if v['table_name']=='sensor_latest']
        if not datasets:raise RuntimeError('Analytics dataset missing')
        identifier=datasets[0]['id']
        data=request(s,'POST','/api/v1/chart/data',json={'datasource':{'id':identifier,'type':'table'},'queries':[{'columns':['sensor','sample_count','average'],'row_limit':1000}],'result_format':'json','result_type':'full'}).json()
        if not data.get('result') or data['result'][0].get('error'):raise RuntimeError('Live analytics chart query failed')
        dashboards=request(s,'GET','/api/v1/dashboard/').json()['result']
        dashboard=next((v for v in dashboards if v['slug']=='data-platform-measurements'),None)
        if dashboard is None:raise RuntimeError('Published dashboard missing')
        charts=request(s,'GET','/api/v1/dashboard/'+str(dashboard['id'])+'/charts').json()['result']
        if len(charts)!=2:raise RuntimeError('Dashboard charts missing')
        for chart in charts:
            detail=request(s,'GET','/api/v1/chart/'+str(chart['id'])).json()['result']
            context=detail.get('query_context')
            if isinstance(context,str):context=json.loads(context)
            if not context:raise RuntimeError('Chart query configuration missing')
            result=request(s,'POST','/api/v1/chart/data',json=context).json()
            if not result.get('result') or result['result'][0].get('error'):raise RuntimeError('Saved dashboard chart failed')
        print('SUPERSET_ANALYTICS_QUERY_OK')
    print('APACHE_SUPERSET_SMOKE_OK')
if __name__=='__main__':
    try:main()
    except Exception as error:
        print('SUPERSET_CHECK_FAILED: '+(str(error) if type(error) is RuntimeError else type(error).__name__),file=sys.stderr)
        sys.exit(1)
