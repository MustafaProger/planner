const {defineConfig}=require('@playwright/test');

module.exports=defineConfig({
 testDir:'./tests',
 testMatch:'test_sidebar_scroll.cjs',
 outputDir:'.local/playwright-sidebar',
 timeout:15000,
 globalTimeout:45000,
 expect:{timeout:3000},
 workers:1,
 retries:0,
 reporter:'line',
 use:{
  browserName:'chromium',
  headless:true,
  actionTimeout:3000,
  navigationTimeout:5000,
  serviceWorkers:'block',
  launchOptions:{timeout:10000,...(process.env.PLAYWRIGHT_CHANNEL?{channel:process.env.PLAYWRIGHT_CHANNEL}:{})},
 },
 projects:[
  {name:'desktop',use:{viewport:{width:1440,height:700}}},
  {name:'mobile',use:{viewport:{width:390,height:600}}},
 ],
});
