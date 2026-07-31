package interceptor

import (
	"encoding/csv"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
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
	case "/dashboard/save_events":
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var evs []SecurityEvent
		if err := json.NewDecoder(r.Body).Decode(&evs); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		// Write directly to the AI dataset (HITL)
		f, err := os.OpenFile("/app/ai-data/wordpress_normal.csv", os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		defer f.Close()
		cw := csv.NewWriter(f)
		for _, ev := range evs {
			// HITL: User selected them, so they are explicitly normal (0)
			// OVERSAMPLING: We force the AI to build a safe cluster by writing 500 copies
			isAnom := "0"
			for i := 0; i < 500; i++ {
				cw.Write([]string{ev.Path, ev.Method, ev.Body, ev.ContentType, isAnom})
			}
		}
		cw.Flush()
		w.WriteHeader(http.StatusOK)
	case "/dashboard/retrain":
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		resp, err := http.Post("http://ai-service:8000/retrain", "application/json", nil)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		defer resp.Body.Close()
		w.WriteHeader(resp.StatusCode)
	case "/dashboard/download_dataset":
		w.Header().Set("Content-Disposition", "attachment; filename=wordpress_normal.csv")
		w.Header().Set("Content-Type", "text/csv")
		http.ServeFile(w, r, "/app/ai-data/wordpress_normal.csv")
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
 table{width:100%;border-collapse:collapse;font-size:14px;}
 th,td{padding:6px;text-align:left;border-bottom:1px solid #eee}
 th{background:#f7f9fc}
 .btn{padding:6px 12px;background:#28a745;color:white;border:none;border-radius:4px;cursor:pointer;font-weight:bold;margin-right:4px;}
 .btn:hover{background:#218838;}
 .btn-dl{padding:10px 16px;background:#007bff;color:white;margin-bottom:16px;display:inline-block;text-decoration:none;border-radius:5px;}
 .btn-dl:hover{background:#0069d9;}
</style>
</head>
<body>
<h1>WAAP Proxy Dashboard</h1>
<a href="/dashboard/download_dataset" download class="btn-dl">📥 Scarica Dataset Aggiuntivo (CSV)</a>
<div class="grid">
 <div class="card"><h2>Statistiche</h2><pre id="stats">Caricamento...</pre></div>
 <div class="card"><h2>Ultimi eventi (Max 2000)</h2><div id="events">Caricamento...</div></div>
</div>
<script>
let currentEvents = [];

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
 currentEvents = data;
 let html='<div style="margin-bottom:10px;"><button class="btn" style="background:#6c757d;" onclick="selectAll()">Tutti</button> <button class="btn" style="background:#6c757d;" onclick="selectByRoute(\'forwarded\')">Solo Forwarded</button> <button class="btn" style="background:#6c757d;" onclick="selectByRoute(\'trapped\')">Solo Trapped</button> <button class="btn" style="background:#dc3545;" onclick="deselectAll()">Nessuno</button> <button class="btn" style="background:#ffc107;color:black;" onclick="saveSelected()">💾 Salva Selezionati</button></div>';
 html+='<table><thead><tr><th><input type="checkbox" onchange="toggleAll(this)"></th><th>Time</th><th>Path</th><th>Score</th><th>Route</th></tr></thead><tbody>';
 for(let idx=data.length-1; idx>=0; idx--){
   const ev=data[idx];
   html += '<tr><td><input type="checkbox" class="ev-chk" value="'+idx+'"></td><td>' + new Date(ev.timestamp).toLocaleTimeString() + '</td><td>' + ev.path + '</td><td>' + ev.risk_score.toFixed(4) + '</td><td>' + ev.routed + '</td></tr>';
 }
 html += '</tbody></table>';
 document.getElementById('events').innerHTML=html;
}

function selectAll(){ document.querySelectorAll('.ev-chk').forEach(c=>c.checked=true); }
function deselectAll(){ document.querySelectorAll('.ev-chk').forEach(c=>c.checked=false); }
function toggleAll(el){ document.querySelectorAll('.ev-chk').forEach(c=>c.checked=el.checked); }
function selectByRoute(r){
 document.querySelectorAll('.ev-chk').forEach(c=>{
   c.checked = (currentEvents[c.value].routed === r);
 });
}

async function saveSelected() {
 const selected = Array.from(document.querySelectorAll('.ev-chk:checked')).map(c => currentEvents[c.value]);
 if(selected.length === 0){ alert("Nessun evento selezionato!"); return; }
 try {
  const res = await fetch('/dashboard/save_events', {
   method: 'POST',
   headers: {'Content-Type': 'application/json'},
   body: JSON.stringify(selected)
  });
  if(res.ok){
   alert("✅ " + selected.length + " eventi salvati nel dataset!");
   deselectAll();
  } else {
   alert("❌ Errore durante il salvataggio.");
  }
 } catch(e) {
  alert("❌ Errore di rete durante il salvataggio.");
 }
}

loadStats(); loadEvents();
setInterval(()=>{
  loadStats();
  if(document.querySelectorAll('.ev-chk:checked').length === 0) {
    loadEvents();
  }
},3000);
</script>
</body>
</html>`
}
