/* seriea-stats v2 1789996138 */
self.addEventListener('install',e=>self.skipWaiting());
self.addEventListener('activate',e=>self.clients.claim());
self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET')return;
  e.respondWith(caches.open('seriea-v1').then(c=>
    c.match(e.request).then(r=>r||fetch(e.request).then(res=>{
      if(res.ok)c.put(e.request,res.clone());return res;
    }).catch(()=>c.match(e.request)))));
});
