
const TD_BASE = "https://api.twelvedata.com/time_series";
const FRED_BASE = "https://api.stlouisfed.org/fred/series/observations";

const tdAssets = [
  ["SPY","S&P 500"],
  ["QQQ","Nasdaq 100"],
  ["XLF","Financials"],
  ["XLK","Technology"],
  ["XLE","Energy"],
  ["GLD","Gold"],
  ["USO","Oil"],
  ["UUP","US Dollar"]
];

const fredSeries = [
  ["DGS2","2Y"],
  ["DGS5","5Y"],
  ["DGS10","10Y"],
  ["DGS30","30Y"]
];

function mean(a){ return a.reduce((s,x)=>s+x,0)/a.length; }
function std(a){
  if(a.length<2) return 0;
  const m=mean(a);
  return Math.sqrt(a.reduce((s,x)=>s+(x-m)**2,0)/(a.length-1));
}
function returns(vals){
  const r=[]; for(let i=1;i<vals.length;i++) if(vals[i-1] && vals[i]) r.push(vals[i]/vals[i-1]-1);
  return r;
}
function corr(a,b){
  const n=Math.min(a.length,b.length); if(n<3) return null;
  a=a.slice(-n); b=b.slice(-n);
  const ma=mean(a),mb=mean(b),sa=std(a),sb=std(b); if(!sa||!sb)return 0;
  return a.reduce((s,x,i)=>s+(x-ma)*(b[i]-mb),0)/((n-1)*sa*sb);
}
function percentile(arr,x){
  if(!arr.length)return null; return 100*arr.filter(v=>v<=x).length/arr.length;
}
async function getTD(symbol,key){
  const u=new URL(TD_BASE);
  u.searchParams.set("symbol",symbol); u.searchParams.set("interval","1day");
  u.searchParams.set("outputsize","260"); u.searchParams.set("apikey",key);
  const r=await fetch(u,{headers:{"accept":"application/json"}});
  const j=await r.json();
  if(!r.ok || !j.values) throw new Error(`Twelve Data ${symbol}: ${j.message||r.status}`);
  return j.values.slice().reverse().map(x=>({date:x.datetime,close:Number(x.close)})).filter(x=>Number.isFinite(x.close));
}
async function getFred(id,key){
  const u=new URL(FRED_BASE);
  u.searchParams.set("series_id",id);u.searchParams.set("api_key",key);u.searchParams.set("file_type","json");
  u.searchParams.set("sort_order","asc");
  const r=await fetch(u); const j=await r.json();
  if(!r.ok || !j.observations) throw new Error(`FRED ${id}: ${j.error_message||r.status}`);
  return j.observations.map(x=>({date:x.date,value:Number(x.value)})).filter(x=>Number.isFinite(x.value));
}
function summarize(label,symbol,series,source){
  const vals=series.map(x=>x.close ?? x.value);
  const rets=returns(vals);
  const latest=vals.at(-1);
  const c1=vals.length>1?(latest/vals.at(-2)-1)*100:null;
  const c20=vals.length>20?(latest/vals.at(-21)-1)*100:null;
  const daily=rets.map(x=>x*100), sd=std(daily), m=mean(daily);
  const z=(c1!==null&&sd)?(c1-m)/sd:null;
  return {label,symbol,latest,change1d:c1,change20d:c20,z1d:z,percentile:c1===null?null:percentile(daily,c1),source};
}
function demo(){
  const assets=[
   {label:"S&P 500",symbol:"SPY",latest:681.2,change1d:-0.7,change20d:2.3,z1d:-1.1,percentile:18,source:"DEMO"},
   {label:"Nasdaq 100",symbol:"QQQ",latest:612.4,change1d:-1.0,change20d:3.1,z1d:-1.3,percentile:13,source:"DEMO"},
   {label:"Financials",symbol:"XLF",latest:55.1,change1d:-0.3,change20d:1.4,z1d:-0.5,percentile:31,source:"DEMO"},
   {label:"Technology",symbol:"XLK",latest:292.8,change1d:-1.2,change20d:3.5,z1d:-1.5,percentile:8,source:"DEMO"},
   {label:"Energy",symbol:"XLE",latest:94.2,change1d:0.8,change20d:4.7,z1d:1.1,percentile:81,source:"DEMO"},
   {label:"Gold",symbol:"GLD",latest:361.4,change1d:0.4,change20d:1.9,z1d:0.6,percentile:69,source:"DEMO"},
   {label:"Oil",symbol:"USO",latest:78.6,change1d:1.1,change20d:5.2,z1d:1.2,percentile:84,source:"DEMO"},
   {label:"US Dollar",symbol:"UUP",latest:29.8,change1d:0.2,change20d:0.7,z1d:0.8,percentile:73,source:"DEMO"}
  ];
  const labs=["SPY","QQQ","XLF","XLK","XLE","GLD","USO","UUP"];
  const matrix=[[1,.91,.68,.86,.31,-.15,.28,-.36],[.91,1,.55,.94,.18,-.12,.20,-.42],[.68,.55,1,.47,.40,-.03,.26,-.16],[.86,.94,.47,1,.15,-.11,.17,-.44],[.31,.18,.40,.15,1,.10,.65,.08],[-.15,-.12,-.03,-.11,.10,1,.22,-.50],[.28,.20,.26,.17,.65,.22,1,.14],[-.36,-.42,-.16,-.44,.08,-.50,.14,1]];
  return {mode:"DEMO",generatedAt:new Date().toISOString(),assets,correlation:{labels:labs,matrix},rates:{curve:[{tenor:"2Y",value:4.21},{tenor:"5Y",value:4.08},{tenor:"10Y",value:4.32},{tenor:"30Y",value:4.67}]},meta:{equitySeries:8,rateSeries:4,correlationPairs:28}};
}
export default async function handler(req,res){
  res.setHeader("Cache-Control","s-maxage=900, stale-while-revalidate=3600");
  const tdKey=process.env.TWELVE_DATA_API_KEY;
  const fredKey=process.env.FRED_API_KEY;
  if(!tdKey || !fredKey) return res.status(200).json(demo());
  try{
    const td = await Promise.all(tdAssets.map(async ([s,l])=>[s,l,await getTD(s,tdKey)]));
    const rates = await Promise.all(fredSeries.map(async ([id,tenor])=>[id,tenor,await getFred(id,fredKey)]));
    const assets=td.map(([s,l,series])=>summarize(l,s,series,"Twelve Data"));
    const labels=td.map(x=>x[0]);
    const retMap=Object.fromEntries(td.map(([s,,series])=>[s,returns(series.map(x=>x.close)).slice(-20)]));
    const matrix=labels.map(a=>labels.map(b=>a===b?1:corr(retMap[a],retMap[b])));
    const curve=rates.map(([id,tenor,series])=>({tenor,value:series.at(-1)?.value??null,series:id}));
    return res.status(200).json({mode:"LIVE",generatedAt:new Date().toISOString(),assets,correlation:{labels,matrix},rates:{curve},meta:{equitySeries:td.length,rateSeries:rates.length,correlationPairs:labels.length*(labels.length-1)/2}});
  }catch(err){
    const d=demo(); d.mode="DEMO_FALLBACK"; d.error=String(err.message||err); return res.status(200).json(d);
  }
}
