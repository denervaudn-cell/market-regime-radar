
const TD="https://api.twelvedata.com/time_series";
const FRED_CSV="https://fred.stlouisfed.org/graph/fredgraph.csv?id=";

const sectors=["XLB","XLC","XLE","XLF","XLI","XLK","XLP","XLRE","XLU","XLV","XLY"];
const benchmark="SPY";
const FULL_UNIVERSE_START="2018-06-19";

const exposure={
 XLB:{rates:-.1,inflation:.8,vol:-.2,credit:-.1,value:.4},
 XLC:{rates:-.4,inflation:0,vol:-.2,credit:0,value:-.3},
 XLE:{rates:.1,inflation:1,vol:-.1,credit:0,value:.8},
 XLF:{rates:.8,inflation:.2,vol:-.1,credit:-.5,value:.8},
 XLI:{rates:.1,inflation:.5,vol:-.2,credit:-.2,value:.4},
 XLK:{rates:-1,inflation:-.2,vol:-.4,credit:0,value:-1},
 XLP:{rates:-.3,inflation:.1,vol:.7,credit:.2,value:.2},
 XLRE:{rates:-1,inflation:.2,vol:-.3,credit:-.8,value:.1},
 XLU:{rates:-1,inflation:0,vol:.5,credit:-.2,value:.2},
 XLV:{rates:-.2,inflation:0,vol:.7,credit:.2,value:.2},
 XLY:{rates:-.6,inflation:-.2,vol:-.5,credit:-.4,value:-.4}
};

function mean(a){return a.reduce((s,x)=>s+x,0)/a.length}
function std(a){if(a.length<2)return 0;const m=mean(a);return Math.sqrt(a.reduce((s,x)=>s+(x-m)**2,0)/(a.length-1))}
function z(arr,x){const s=std(arr);return s?(x-mean(arr))/s:0}
function clamp(x,a,b){return Math.max(a,Math.min(b,x))}
function ret(a,b){return a&&b?b/a-1:null}
function weighted(names,weights,prices,m,next){return names.reduce((s,n,i)=>s+ret(prices[n].get(m),prices[n].get(next))*weights[i],0)}

async function tdSeries(symbol,key,start){
  const u=new URL(TD);
  u.searchParams.set("symbol",symbol);
  u.searchParams.set("interval","1day");
  u.searchParams.set("start_date",start);
  u.searchParams.set("outputsize","5000");
  u.searchParams.set("adjust","all");
  u.searchParams.set("apikey",key);
  const r=await fetch(u);
  const j=await r.json();
  if(!r.ok||!j.values)throw new Error(`Twelve Data ${symbol}: ${j.message||r.status}`);
  return j.values.slice().reverse().map(x=>({date:x.datetime,v:Number(x.close)})).filter(x=>Number.isFinite(x.v));
}
async function fred(id,start){
  const r=await fetch(FRED_CSV+encodeURIComponent(id));
  if(!r.ok)throw new Error(`FRED ${id}: ${r.status}`);
  const t=await r.text(), lines=t.trim().split(/\r?\n/), out=[];
  for(let i=1;i<lines.length;i++){
    const [date,val]=lines[i].split(",");
    const v=Number(val);
    if(date>=start && Number.isFinite(v))out.push({date,v});
  }
  return out;
}
function monthEnd(series){
  const m=new Map();
  for(const x of series)m.set(x.date.slice(0,7),x);
  return [...m.entries()].map(([month,x])=>({month,date:x.date,v:x.v}));
}
function monthlyMap(series){return new Map(monthEnd(series).map(x=>[x.month,x.v]))}
function previousMonths(keys,idx,n){return keys.slice(Math.max(0,idx-n),idx)}
function stats(rets,hitAgainst=null,turnover=0){
  if(!rets.length)return {};
  const growth=rets.reduce((a,r)=>a*(1+r),1), years=rets.length/12;
  const cagr=Math.pow(growth,1/years)-1, annVol=std(rets)*Math.sqrt(12);
  let eq=1,peak=1,mdd=0;
  for(const r of rets){eq*=1+r;peak=Math.max(peak,eq);mdd=Math.min(mdd,eq/peak-1)}
  return {cagr,annVol,sharpe:annVol?cagr/annVol:null,maxDrawdown:mdd,
    hitRate:hitAgainst?rets.filter((r,i)=>r>hitAgainst[i]).length/rets.length:null,
    turnover,avgHoldings:1};
}
function yearly(rows){
  const by={};
  rows.forEach(x=>{const y=x.date.slice(0,4);(by[y]??=[]).push(x)});
  return Object.entries(by).map(([year,a])=>{
    const s=a.reduce((g,x)=>g*(1+x.sret),1)-1;
    const b=a.reduce((g,x)=>g*(1+x.bret),1)-1;
    return {year,strategy:s,benchmark:b,excess:s-b};
  });
}

async function loadDataset(tdKey,start){
  // Sequential batches reduce burst-rate failures on low-tier Twelve Data plans.
  const symbols=[...sectors,benchmark];
  const pricePairs=[];
  for(let i=0;i<symbols.length;i+=4){
    const batch=symbols.slice(i,i+4);
    const vals=await Promise.all(batch.map(async s=>[s,await tdSeries(s,tdKey,start)]));
    pricePairs.push(...vals);
    if(i+4<symbols.length) await new Promise(r=>setTimeout(r,1200));
  }
  const [dgs2,dgs10,real10,bei10,vix,hy,dff]=await Promise.all([
    fred("DGS2",start),fred("DGS10",start),fred("DFII10",start),fred("T10YIE",start),
    fred("VIXCLS",start),fred("BAMLH0A0HYM2",start),fred("DFF",start)
  ]);
  return {
    prices:Object.fromEntries(pricePairs.map(([s,a])=>[s,monthlyMap(a)])),
    macro:{
      dgs2:monthlyMap(dgs2),dgs10:monthlyMap(dgs10),real10:monthlyMap(real10),
      bei10:monthlyMap(bei10),vix:monthlyMap(vix),hy:monthlyMap(hy),dff:monthlyMap(dff)
    }
  };
}

function buildBaseRows(dataset,start){
  const {prices,macro}=dataset;
  const keys=[...prices[benchmark].keys()].filter(k=>k>=start.slice(0,7)).sort();
  const base=[];
  for(let i=13;i<keys.length-1;i++){
    const m=keys[i],next=keys[i+1];
    if(![macro.dgs2,macro.dgs10,macro.real10,macro.bei10,macro.vix,macro.hy,macro.dff].every(mp=>mp.has(m)))continue;
    if(![...sectors,benchmark].every(s=>prices[s].has(m)&&prices[s].has(next)))continue;

    const hist=previousMonths(keys,i,60);
    const slope=macro.dgs10.get(m)-macro.dgs2.get(m);
    const slopes=hist.filter(x=>macro.dgs10.has(x)&&macro.dgs2.has(x)).map(x=>macro.dgs10.get(x)-macro.dgs2.get(x));
    const reals=hist.filter(x=>macro.real10.has(x)).map(x=>macro.real10.get(x));
    const beis=hist.filter(x=>macro.bei10.has(x)).map(x=>macro.bei10.get(x));
    const vxs=hist.filter(x=>macro.vix.has(x)).map(x=>macro.vix.get(x));
    const credits=hist.filter(x=>macro.hy.has(x)).map(x=>macro.hy.get(x));
    if([slopes,reals,beis,vxs,credits].some(a=>a.length<12))continue;

    const state={
      rates:clamp(z(reals,macro.real10.get(m))/2,-1,1),
      curve:clamp(z(slopes,slope)/2,-1,1),
      inflation:clamp(z(beis,macro.bei10.get(m))/2,-1,1),
      vol:clamp(z(vxs,macro.vix.get(m))/2,-1,1),
      credit:clamp(z(credits,macro.hy.get(m))/2,-1,1)
    };

    const scored=[];
    for(const s of sectors){
      const past6=keys[i-6],mp=prices[s];
      if(!past6||!mp.has(past6))continue;
      const momentum=ret(mp.get(past6),mp.get(m)),e=exposure[s];
      const macroScore=(-state.rates)*e.rates*18+state.curve*e.rates*12+state.inflation*e.inflation*14+(-state.vol)*e.vol*10+(-state.credit)*e.credit*12+e.value*(state.rates*.25+state.inflation*.25)*8;
      const momScore=clamp(momentum/.20,-1,1)*22;
      scored.push({s,score:50+macroScore+momScore});
    }
    if(scored.length!==sectors.length)continue;
    scored.sort((a,b)=>b.score-a.score);
    base.push({m,next,scored,state,bret:ret(prices[benchmark].get(m),prices[benchmark].get(next)),funding:macro.dff.get(m)/100});
  }
  return {base,prices};
}

function runMode(mode,baseData,costBps,shortBorrowBps){
  const {base,prices}=baseData;
  const rows=[];let prevLong=[],turnoverSum=0;
  for(const x of base){
    const {m,next,scored,state,bret,funding}=x;
    let longs,shorts,weights;
    if(mode==="longonly3"){longs=scored.slice(0,3).map(x=>x.s);shorts=[];weights=[1,.65,.45]}
    else {longs=[scored[0].s];shorts=[scored.at(-1).s];weights=[1]}

    const turnover=prevLong.length?1-longs.filter(s=>prevLong.includes(s)).length/longs.length:1;
    prevLong=longs;turnoverSum+=turnover;

    const lret=weighted(longs,weights,prices,m,next);
    const sret0=shorts.length?weighted(shorts,weights,prices,m,next):0;
    const monthlyFunding=funding/12, monthlyBorrow=(shortBorrowBps/10000)/12;
    let sret,longRet,shortRet;

    if(mode==="longonly3"){
      longRet=lret;shortRet=0;
      sret=longRet-turnover*(costBps/10000)*2.10-1.10*monthlyFunding;
    }else{
      longRet=2*lret;shortRet=2*sret0;
      sret=longRet-shortRet-turnover*(costBps/10000)*2-monthlyFunding-2*monthlyBorrow;
    }
    rows.push({date:next,sret,bret,longRet,shortRet,longs,shorts,state,fundingRate:funding});
  }
  if(rows.length<12)throw new Error("Not enough overlapping real history.");

  let se=100,be=100;const equityCurve=[];
  for(const x of rows){se*=1+x.sret;be*=1+x.bret;equityCurve.push({date:x.date,strategy:+se.toFixed(2),benchmark:+be.toFixed(2)})}
  const srets=rows.map(x=>x.sret),brets=rows.map(x=>x.bret);
  return {
    stats:{strategy:stats(srets,brets,turnoverSum/(rows.length/12)),benchmark:stats(brets)},
    equityCurve,annual:yearly(rows),
    latest:{longs:rows.at(-1).longs,shorts:rows.at(-1).shorts,state:rows.at(-1).state},
    holdings:rows.map(x=>({date:x.date,longs:x.longs,shorts:x.shorts,excess:x.sret-x.bret}))
  };
}

export default async function handler(req,res){
  res.setHeader("Cache-Control","s-maxage=1800, stale-while-revalidate=3600");
  const tdKey=process.env.TWELVE_DATA_API_KEY;
  if(!tdKey)return res.status(503).json({ok:false,error:"TWELVE_DATA_API_KEY is missing."});

  const requestedStart=req.query.start||"2020-01-01";
  const start=requestedStart<FULL_UNIVERSE_START?FULL_UNIVERSE_START:requestedStart;
  const costBps=Math.max(0,Number(req.query.costBps)||10);
  const shortBorrowBps=Math.max(0,Number(req.query.shortBorrowBps)||50);
  const mode=req.query.mode||"extreme1";

  try{
    const dataset=await loadDataset(tdKey,start);
    const baseData=buildBaseRows(dataset,start);

    if(mode==="compare"){
      const ls=runMode("extreme1",baseData,costBps,shortBorrowBps);
      const lo=runMode("longonly3",baseData,costBps,0);
      return res.status(200).json({
        ok:true,
        meta:{start:ls.equityCurve[0].date,end:ls.equityCurve.at(-1).date,months:ls.equityCurve.length,costBps,shortBorrowBps,source:"Single shared real-data load"},
        longshort:ls,longonly:lo,benchmark:ls.stats.benchmark
      });
    }

    const out=runMode(mode,baseData,costBps,shortBorrowBps);
    return res.status(200).json({
      ok:true,
      meta:{start:out.equityCurve[0].date,end:out.equityCurve.at(-1).date,months:out.equityCurve.length,rebalance:"monthly",costBps,shortBorrowBps,mode,source:"Twelve Data + FRED public CSV"},
      ...out
    });
  }catch(e){
    return res.status(500).json({ok:false,error:String(e.message||e)});
  }
}
