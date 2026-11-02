# Source: FINAL-Building_Energy_Study.ipynb, training cell; only the output path is adapted.
"""Reproducible UCI Energy Efficiency experiment. Run: python train_models.py.
All reported metrics are measured against simulated responses, not field energy use.
"""
from pathlib import Path
import argparse, hashlib, json, os, platform, sys, time, urllib.request, zipfile
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
import numpy as np
import pandas as pd
import sklearn
import joblib
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.pipeline import Pipeline
from sklearn.linear_model import LinearRegression
from sklearn.tree import DecisionTreeRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.dummy import DummyRegressor
from sklearn.model_selection import train_test_split, KFold, GroupKFold, LeaveOneGroupOut, GridSearchCV
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.inspection import permutation_importance
from threadpoolctl import threadpool_limits
ROOT=Path(__file__).resolve().parent / 'energy_study'
ROOT.mkdir(parents=True, exist_ok=True)
FEATURES=['X'+str(i) for i in range(1,9)]
CONT=['X1','X2','X3','X4','X5','X7']; CAT=['X6','X8']
SEED=42
URL='https://archive.ics.uci.edu/static/public/242/energy+efficiency.zip'
NAMES={'X1':'Relative compactness','X2':'Surface area','X3':'Wall area','X4':'Roof area','X5':'Overall height','X6':'Orientation','X7':'Glazing area','X8':'Glazing distribution'}
def dump(obj,path):
 Path(path).write_text(json.dumps(obj,indent=2,default=lambda x:x.item() if hasattr(x,'item') else str(x)))
def load_data(root=ROOT):
 d=root/'data';d.mkdir(exist_ok=True,parents=True);f=d/'ENB2012_data.xlsx'
 if not f.exists():
  urllib.request.urlretrieve(URL,d/'energy_efficiency.zip')
  with zipfile.ZipFile(d/'energy_efficiency.zip') as z:f.write_bytes(z.read('ENB2012_data.xlsx'))
 df=pd.read_excel(f).dropna(how='all')
 assert list(df.columns)==FEATURES+['Y1','Y2'], 'Unexpected columns'
 assert df.shape==(768,10), 'Unexpected dataset size'
 assert not df.isna().any().any(), 'Missing data require an explicit policy'
 assert not df[FEATURES].duplicated().any(), 'Duplicate predictors need grouped splitting'
 groups=pd.factorize(pd.MultiIndex.from_frame(df[FEATURES[:5]]),sort=True)[0]
 assert len(np.unique(groups))==12
 return df,groups,f

def make_model(name):
 prep=ColumnTransformer([('continuous',StandardScaler() if name=='MLR' else 'passthrough',CONT),('categorical',OneHotEncoder(drop='first',handle_unknown='ignore',sparse_output=False),CAT)])
 model={'MLR':LinearRegression(),'DT':DecisionTreeRegressor(random_state=SEED),'RF':RandomForestRegressor(n_estimators=100,random_state=SEED,n_jobs=1)}[name]
 return Pipeline([('preprocess',prep),('model',model)])
def grid(name):
 if name=='MLR':return {}
 g={'model__max_depth':[3,5,10,None],'model__min_samples_leaf':[1,2,5]}
 if name=='RF':g['model__max_features']=[0.5,1.0]
 return g

def metrics(y,p):
 return {'MAE':float(mean_absolute_error(y,p)),'RMSE':float(np.sqrt(mean_squared_error(y,p))),'R2':float(r2_score(y,p))}

def tune(name,X,y,cv,jobs,groups=None):
 search=GridSearchCV(make_model(name),grid(name),cv=cv,scoring={'mae':'neg_mean_absolute_error','rmse':'neg_root_mean_squared_error','r2':'r2'},refit='mae',n_jobs=jobs,error_score='raise',return_train_score=True)
 start=time.perf_counter();search.fit(X,y,groups=groups);elapsed=time.perf_counter()-start
 return search,elapsed

def timing(model,X,y,test):
 fits=[]
 for _ in range(5):
  t=time.perf_counter();clone(model).fit(X,y);fits.append(1000*(time.perf_counter()-t))
 row=test.iloc[[0]]
 for _ in range(100):model.predict(row)
 calls=[]
 for _ in range(1000):
  t=time.perf_counter();model.predict(row);calls.append(1000*(time.perf_counter()-t))
 batch=[]
 for _ in range(30):
  t=time.perf_counter();model.predict(test);batch.append(1000*(time.perf_counter()-t))
 return {'fit_median_ms':float(np.median(fits)),'fit_iqr_ms':float(np.subtract(*np.percentile(fits,[75,25]))),'single_median_ms':float(np.median(calls)),'single_iqr_ms':float(np.subtract(*np.percentile(calls,[75,25]))),'batch_median_ms':float(np.median(batch))}

def generate_plots(root=ROOT):
 """Create diagnostic charts from saved predictions without refitting models."""
 import matplotlib
 matplotlib.use('Agg')
 import matplotlib.pyplot as plt
 out=root/'results';figdir=out/'figures';figdir.mkdir(exist_ok=True)
 pp=pd.read_csv(out/'test_predictions.csv')
 for target,label in [('Y1','Heating'),('Y2','Cooling')]:
  fig,axes=plt.subplots(2,3,figsize=(13,7))
  for j,name in enumerate(['MLR','DT','RF']):
   g=pp[(pp.target==target)&(pp.model==name)]
   lo=min(g.actual.min(),g.predicted.min());hi=max(g.actual.max(),g.predicted.max())
   axes[0,j].scatter(g.actual,g.predicted,s=15,alpha=.65,color='#167D8D')
   axes[0,j].plot([lo,hi],[lo,hi],color='#BD6739',linestyle='--')
   axes[0,j].set(title=name,xlabel='Simulated load',ylabel='Predicted load')
   axes[1,j].scatter(g.predicted,g.predicted-g.actual,s=15,alpha=.65,color='#167D8D')
   axes[1,j].axhline(0,color='#BD6739',linestyle='--')
   axes[1,j].set(xlabel='Predicted load',ylabel='Prediction minus simulated load')
  fig.suptitle(label+' load: held-out predictions and residuals (dataset units)')
  fig.tight_layout();fig.savefig(figdir/(target+'_diagnostics.png'),dpi=160);plt.close(fig)
 g=pd.read_csv(out/'shape_fold_results.csv')
 fig,axes=plt.subplots(1,2,figsize=(13,4))
 for ax,target,label in zip(axes,['Y1','Y2'],['Heating','Cooling']):
  for name,color in [('MLR','#163347'),('DT','#BD6739'),('RF','#167D8D')]:
   h=g[(g.target==target)&(g.model==name)].sort_values('shape_group')
   ax.plot(h.shape_group,h.MAE,marker='o',label=name,color=color)
  ax.set(title=label,xlabel='Excluded shape group',ylabel='MAE (dataset units)');ax.legend()
 fig.tight_layout();fig.savefig(figdir/'unseen_shape_errors.png',dpi=160);plt.close(fig)

def main(jobs=2,root=ROOT):
 start=time.perf_counter();out=root/'results';out.mkdir(exist_ok=True);(root/'models').mkdir(exist_ok=True)
 df,groups,file=load_data(root);X=df[FEATURES]
 train,test=train_test_split(np.arange(len(df)),test_size=.2,random_state=SEED)
 assert not set(train)&set(test)
 splits=pd.DataFrame({'row_id':np.arange(768),'shape_group':groups,'partition':['development' if i in set(train) else 'test' for i in range(768)]});splits.to_csv(out/'splits.csv',index=False)
 df[FEATURES].corr().to_csv(out/'feature_correlations.csv')
 info={'source_url':URL,'source_doi':'10.24432/C51307','data_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'rows':len(df),'features':FEATURES,'shapes':12,'development_n':len(train),'test_n':len(test),'seed':SEED,'python':sys.version,'sklearn':sklearn.__version__,'numpy':np.__version__,'pandas':pd.__version__,'joblib':joblib.__version__,'platform':platform.platform(),'cpu':platform.processor(),'logical_cpus':os.cpu_count(),'grid_jobs':jobs,'estimator_jobs':1,'units':'Original dataset load units; repository does not specify physical units.','missing_values':int(df.isna().sum().sum()),'duplicate_predictors':int(df[FEATURES].duplicated().sum())}
 dump(info,out/'run_metadata.json')
 rows=[];predictions=[];selected={};models={};importance=[]
 cv=KFold(n_splits=5,shuffle=True,random_state=SEED)
 for target in ['Y1','Y2']:
  y=df[target]
  dummy=DummyRegressor().fit(X.iloc[train],y.iloc[train]);dp=dummy.predict(X.iloc[test]);rows.append({'target':target,'model':'Mean baseline',**metrics(y.iloc[test],dp)})
  for name in ['MLR','DT','RF']:
   search,elapsed=tune(name,X.iloc[train],y.iloc[train],cv,jobs)
   model=search.best_estimator_;models[target,name]=model;idx=search.best_index_;res=search.cv_results_
   pred=model.predict(X.iloc[test]);ms=timing(model,X.iloc[train],y.iloc[train],X.iloc[test])
   row={'target':target,'model':name,**metrics(y.iloc[test],pred),'cv_MAE':-res['mean_test_mae'][idx],'cv_MAE_sd':res['std_test_mae'][idx],'cv_RMSE':-res['mean_test_rmse'][idx],'cv_R2':res['mean_test_r2'][idx],'train_MAE':mean_absolute_error(y.iloc[train],model.predict(X.iloc[train])),'search_seconds':elapsed,**ms,'parameters':search.best_params_}
   rows.append(row);joblib.dump(model,root/'models'/f'{target}_{name}_development.joblib')
   pd.DataFrame(res).to_csv(out/f'cv_{target}_{name}.csv',index=False)
   predictions.extend({'row_id':int(r),'target':target,'model':name,'actual':float(y.iloc[r]),'predicted':float(p)} for r,p in zip(test,pred))
   print('PRIMARY',target,name,json.dumps({k:row[k] for k in ['MAE','RMSE','R2','cv_MAE']}),flush=True)
  candidates=[r for r in rows if r['target']==target and r['model']!='Mean baseline'];best=min(r['cv_MAE'] for r in candidates)
  eligible=[r for r in candidates if r['cv_MAE']<=1.01*best]
  winner=min(eligible,key=lambda r:(r['cv_RMSE'],r['single_median_ms'],['MLR','DT','RF'].index(r['model'])))['model'];selected[target]=winner
  pi=permutation_importance(models[target,winner],X.iloc[test],y.iloc[test],scoring='neg_mean_absolute_error',n_repeats=30,random_state=SEED,n_jobs=jobs)
  importance.extend({'target':target,'model':winner,'feature':f,'label':NAMES[f],'MAE_increase':float(m),'sd':float(s)} for f,m,s in zip(FEATURES,pi.importances_mean,pi.importances_std))
 dump(selected,out/'selected_models.json');dump(rows,out/'primary_results.json');pd.DataFrame(rows).to_csv(out/'primary_results.csv',index=False);pd.DataFrame(predictions).to_csv(out/'test_predictions.csv',index=False);pd.DataFrame(importance).to_csv(out/'permutation_importance.csv',index=False)
 # Nested validation by complete building shape. No held-out-shape tuning.
 group_rows=[];group_predictions=[];logo=LeaveOneGroupOut()
 for target in ['Y1','Y2']:
  y=df[target]
  for fold,(tr,te) in enumerate(logo.split(X,y,groups)):
   assert not set(groups[tr])&set(groups[te])
   for name in ['MLR','DT','RF']:
    search,elapsed=tune(name,X.iloc[tr],y.iloc[tr],GroupKFold(3),jobs,groups[tr]);p=search.predict(X.iloc[te])
    group_rows.append({'target':target,'model':name,'shape_group':int(groups[te][0]),'n':len(te),**metrics(y.iloc[te],p),'parameters':search.best_params_})
    group_predictions.extend({'row_id':int(r),'shape_group':int(groups[r]),'target':target,'model':name,'actual':float(y.iloc[r]),'predicted':float(v)} for r,v in zip(te,p))
   print('GROUP',target,fold+1,'/12 complete',flush=True)
   pd.DataFrame(group_rows).to_csv(out/'shape_fold_results.csv',index=False)
   pd.DataFrame(group_predictions).to_csv(out/'shape_predictions.csv',index=False)
 group_df=pd.DataFrame(group_predictions);summary=[]
 for (target,name),g in group_df.groupby(['target','model']):
  fs=pd.DataFrame(group_rows);fs=fs[(fs.target==target)&(fs.model==name)]
  summary.append({'target':target,'model':name,**metrics(g.actual,g.predicted),'shape_MAE_sd':float(fs.MAE.std(ddof=1)),'shape_MAE_min':float(fs.MAE.min()),'shape_MAE_max':float(fs.MAE.max())})
 dump(summary,out/'shape_results.json');pd.DataFrame(summary).to_csv(out/'shape_results.csv',index=False)
 # Predeclared demonstration: first lexicographic matched geometry/orientation/
 # glazing-distribution group with >=3 glazing values, selected without outcomes.
 match=['X1','X2','X3','X4','X5','X6','X8']
 candidates=[g for _,g in df.groupby(match,sort=True) if g.X7.nunique()>=3]
 demo=candidates[0].sort_values('X7').copy();demo.insert(0,'row_id',demo.index)
 for target in ['Y1','Y2']:
  pp=group_df[(group_df.target==target)&(group_df.model==selected[target])].set_index('row_id').predicted
  demo[target+'_predicted']=demo.row_id.map(pp)
 demo.to_csv(out/'design_demonstration.csv',index=False)
 generate_plots(root)
 info['total_seconds']=time.perf_counter()-start;info['completed']=True;dump(info,out/'run_metadata.json')
 print('COMPLETE',selected,'seconds',info['total_seconds'],flush=True)
 return {'primary':rows,'shape':summary,'selected':selected}


if __name__ == '__main__':
 with threadpool_limits(limits=1):
  main(jobs=2, root=ROOT)

