"""Idempotent Superset provisioning; secrets stay in protected settings."""
import json
import subprocess
from pathlib import Path
from urllib.parse import quote
from werkzeug.security import check_password_hash
settings=json.loads(Path('/etc/apache-superset/settings.json').read_text())
marker=Path(settings['data_dir'])/'state/.initialized-6.1.0'
changed=False
if not marker.exists():
    subprocess.run(['/opt/apache-superset/bin/superset','init'],check=True,capture_output=True)
    changed=True
from superset.app import create_app
from superset import db
app=create_app()
with app.app_context():
    sm=app.appbuilder.sm
    user=sm.find_user(username='admin')
    if user is None:
        user=sm.add_user('admin','Platform','Administrator','admin@localhost',sm.find_role('Admin'),settings['admin_password'])
        if not user:raise RuntimeError('Administrator creation failed')
        changed=True
    elif not check_password_hash(user.password,settings['admin_password']):
        sm.reset_password(user.id,settings['admin_password']);changed=True
    if settings['analytics_enabled']:
        from superset.models.core import Database
        from superset.connectors.sqla.models import SqlaTable
        from superset.models.slice import Slice
        from superset.models.dashboard import Dashboard
        uri='clickhousedb://platform_reader:'+quote(settings['clickhouse_password'],safe='')+'@'+settings['clickhouse_host']+':8443/analytics'
        extra=json.dumps({'engine_params':{'connect_args':{'secure':True,'verify':True,'ca_cert':'/etc/apache-superset/clickhouse-ca.crt'}}},sort_keys=True)
        database=db.session.query(Database).filter_by(database_name='Data platform analytics').one_or_none()
        if database is None:
            database=Database(database_name='Data platform analytics',sqlalchemy_uri=uri,extra=extra,expose_in_sqllab=True,allow_dml=False)
            db.session.add(database);db.session.flush();changed=True
        elif database.sqlalchemy_uri_decrypted!=uri or database.extra!=extra:
            database.sqlalchemy_uri=uri;database.extra=extra;changed=True
        dataset=db.session.query(SqlaTable).filter_by(database_id=database.id,table_name='sensor_latest',schema='analytics').one_or_none()
        if dataset is None:
            dataset=SqlaTable(table_name='sensor_latest',schema='analytics',database=database,owners=[user])
            db.session.add(dataset);db.session.flush();dataset.fetch_metadata();changed=True
        charts=[]
        specs=[('Measurements - latest values','table',{'query_mode':'raw','all_columns':['sensor','sample_count','total','average'],'row_limit':1000}),('Measurements - sample counts','pie',{'groupby':['sensor'],'metric':{'expressionType':'SIMPLE','column':{'column_name':'sample_count','type':'BIGINT'},'aggregate':'SUM','label':'Samples'},'row_limit':1000,'show_labels':True})]
        for title,viz,params in specs:
            params.update({'datasource':str(dataset.id)+'__table','viz_type':viz})
            value=json.dumps(params,sort_keys=True)
            chart=db.session.query(Slice).filter_by(slice_name=title).one_or_none()
            if chart is None:
                chart=Slice(slice_name=title,viz_type=viz,datasource_type='table',datasource_id=dataset.id,params=value,owners=[user]);db.session.add(chart);changed=True
            elif chart.params!=value:chart.params=value;changed=True
            charts.append(chart)
        db.session.flush()
        dashboard=db.session.query(Dashboard).filter_by(slug='data-platform-measurements').one_or_none()
        if dashboard is None:
            dashboard=Dashboard(dashboard_title='Data platform measurements',slug='data-platform-measurements',published=True,owners=[user]);db.session.add(dashboard);changed=True
        positions={'DASHBOARD_VERSION_KEY':'v2','ROOT_ID':{'id':'ROOT_ID','type':'ROOT','children':['GRID_ID']},'GRID_ID':{'id':'GRID_ID','type':'GRID','children':['ROW-1'],'parents':['ROOT_ID']},'HEADER_ID':{'id':'HEADER_ID','type':'HEADER','meta':{'text':'Data platform measurements'}},'ROW-1':{'id':'ROW-1','type':'ROW','children':['CHART-1','CHART-2'],'parents':['ROOT_ID','GRID_ID'],'meta':{'background':'BACKGROUND_TRANSPARENT'}}}
        for i,chart in enumerate(charts,1):
            key='CHART-'+str(i)
            positions[key]={'id':key,'type':'CHART','children':[],'parents':['ROOT_ID','GRID_ID','ROW-1'],'meta':{'chartId':chart.id,'width':6,'height':50,'sliceName':chart.slice_name}}
        position_json=json.dumps(positions,sort_keys=True)
        if dashboard.position_json!=position_json or {x.id for x in dashboard.slices}!={x.id for x in charts}:
            dashboard.position_json=position_json;dashboard.slices=charts;changed=True
    db.session.commit()
if not marker.exists():marker.write_text('Initialized metadata and roles\n')
print('SUPERSET_PROVISION_CHANGED' if changed else 'SUPERSET_PROVISION_OK')
