/* seriea-v3 1790100000 */
self.addEventListener('install',e=>self.skipWaiting());
self.addEventListener('activate',e=>{
  e.waitUntil(caches.keys().then(ks=>Promise.all(
    ks.filter(k=>k.startsWith('seriea-')&&k!=='seriea-v3').map(k=>caches.delete(k))
  )).then(()=>self.clients.claim()));
});
self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET')return;
  try{
    const u=new URL(e.request.url);
    if(u.origin===location.origin&&u.pathname.startsWith('/api/'))return;
  }catch(err){}
  e.respondWith(caches.open('seriea-v3').then(c=>
    c.match(e.request).then(r=>r||fetch(e.request).then(res=>{
      if(res.ok)c.put(e.request,res.clone());return res;
    }).catch(()=>c.match(e.request)))));
});
