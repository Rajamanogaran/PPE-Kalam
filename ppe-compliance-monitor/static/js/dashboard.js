// Dashboard auto-refresh + stats polling
// Used on index & dashboard pages
(function(){
  const API_STATS = '/api/stats/';
  const API_VIOLS = '/api/violations/';

  class PPEDashboard {
    constructor(opts={}){
      this.interval = opts.interval || 8000;
      this.hours = opts.hours || 24;
      this.init();
    }
    init(){
      this.startPolling();
      console.log('PPE Dashboard JS loaded');
    }
    startPolling(){
      setInterval(()=> this.refresh(), this.interval);
    }
    async refresh(){
      try{
        const res = await fetch(`${API_STATS}?hours=${this.hours}`);
        const stats = await res.json();
        this.updateMetrics(stats);
        // Optionally update charts if Plotly exists and caller wants
        if (window.onDashboardStatsUpdate) window.onDashboardStatsUpdate(stats);
      }catch(e){ console.warn('dashboard refresh failed', e) }
    }
    updateMetrics(stats){
      const map = {
        'm-active': stats.active_violations,
        'side-active': stats.active_violations,
      };
      Object.entries(map).forEach(([id,val])=>{
        const el=document.getElementById(id);
        if(el && val!=null) el.textContent=val;
      });
    }
  }

  // Auto-init if on a page with metrics
  document.addEventListener('DOMContentLoaded', ()=>{
    if(document.getElementById('m-active') || document.getElementById('side-active')){
      window.ppeDashboard = new PPEDashboard({hours: 24});
    }
  });

  window.PPEDashboard = PPEDashboard;
})();
