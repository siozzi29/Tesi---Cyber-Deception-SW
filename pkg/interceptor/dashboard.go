package interceptor

import (
	"encoding/json"
	"fmt"
	"net/http"
)

// DashboardHandler espone le statistiche e gli eventi recenti del proxy.
func (i *SecurityInterceptor) DashboardHandler(w http.ResponseWriter, r *http.Request) {
	stats, events := i.Snapshot()

	switch r.URL.Path {
	case "/dashboard":
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		fmt.Fprint(w, dashboardHTML())
	case "/dashboard/stats":
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(stats)
	case "/dashboard/events":
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(events)
	default:
		http.NotFound(w, r)
	}
}

func dashboardHTML() string {
	return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>WAAP Proxy Dashboard</title>
<style>
 body{font-family:Arial,sans-serif;margin:0;padding:16px;background:#f4f6fb;color:#111}
 h1{margin-bottom:8px}
 .card{background:#fff;border:1px solid #d7dde7;border-radius:10px;padding:16px;margin-bottom:16px;box-shadow:0 2px 10px rgba(0,0,0,.05)}
 .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}
 pre{white-space:pre-wrap;word-break:break-word}
 table{width:100%;border-collapse:collapse}
 th,td{padding:8px;text-align:left;border-bottom:1px solid #eee}
 th{background:#f7f9fc}
</style>
</head>
<body>
<h1>WAAP Proxy Dashboard</h1>
<div class="grid">
 <div class="card"><h2>Statistiche</h2><pre id="stats">Caricamento...</pre></div>
 <div class="card"><h2>Ultimi eventi</h2><div id="events">Caricamento...</div></div>
</div>
<script>
async function loadStats(){
 const res=await fetch('/dashboard/stats');
 const data=await res.json();
 document.getElementById('stats').textContent=JSON.stringify(data,null,2);
}
async function loadEvents(){
 const res=await fetch('/dashboard/events');
 const data=await res.json();
 if(!Array.isArray(data)||data.length===0){
   document.getElementById('events').textContent='Nessun evento ancora.';
   return;
 }
 let html='<table><thead><tr><th>Time</th><th>Path</th><th>Score</th><th>Honey</th><th>Route</th></tr></thead><tbody>';
 for(let idx=data.length-1; idx>=0; idx--){
   const ev=data[idx];
   html += '<tr><td>' + new Date(ev.timestamp).toLocaleTimeString() + '</td><td>' + ev.path + '</td><td>' + ev.risk_score.toFixed(4) + '</td><td>' + ev.is_honey + '</td><td>' + ev.routed + '</td></tr>';
 }
 html += '</tbody></table>';
 document.getElementById('events').innerHTML=html;
}
loadStats(); loadEvents();
setInterval(()=>{loadStats(); loadEvents();},3000);
</script>
</body>
</html>`
}
