// Build: x64 Console, /std:c++17
#include <windows.h>
#include <cstdio>
#include <cstdint>
#include <string>
#include <vector>
#include <sstream>
#include <iostream>
#include <iomanip>
#include <stdexcept>

extern "C" {
  #include <th260defin.h>
  #include <th260lib.h>
}

static int g_dev = -1, g_ch = 0, g_len = 0;
static double g_res = 0;
static std::vector<std::vector<uint32_t>> g_hist;

static const char* B64="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
static std::string b64(const uint8_t* p,size_t n){
  std::string o; o.reserve(((n+2)/3)*4);
  for(size_t i=0;i<n;i+=3){
    uint32_t v=p[i]<<16 | ((i+1<n)?p[i+1]<<8:0) | ((i+2<n)?p[i+2]:0);
    o.push_back(B64[(v>>18)&63]); o.push_back(B64[(v>>12)&63]);
    o.push_back((i+1<n)?B64[(v>>6)&63]:'='); o.push_back((i+2<n)?B64[v&63]:'=');
  } return o;
}
static void pq_throw(const char* what,int rc){
  char err[40]; TH260_GetErrorString(err, rc);
  std::ostringstream s; s<<what<<" "<<rc<<" ("<<err<<")"; throw std::runtime_error(s.str());
}
static void th260_close(){ if(g_dev>=0){ for(int i=0;i<MAXDEVNUM;i++) TH260_CloseDevice(i); g_dev=-1; } }

static void th260_init(int binning,int offset_ps,int sync_div,int sync_offset_ps){
  th260_close();
  char sn[8]={0};
  for(int i=0;i<MAXDEVNUM;i++){ if(TH260_OpenDevice(i,sn)==0){ g_dev=i; break; } }
  if(g_dev<0) throw std::runtime_error("no TH260");
  if(int rc=TH260_Initialize(g_dev, MODE_HIST); rc<0) pq_throw("Initialize", rc);

  char model[16], part[8], ver[16];
  if(int rc=TH260_GetHardwareInfo(g_dev,model,part,ver); rc<0) pq_throw("GetHardwareInfo", rc);
  if(int rc=TH260_GetNumOfInputChannels(g_dev,&g_ch); rc<0) pq_throw("GetNumChannels", rc);
  if(int rc=TH260_SetSyncDiv(g_dev,sync_div); rc<0) pq_throw("SetSyncDiv", rc);

  if(std::string(model)=="TimeHarp 260 P"){
    if(int rc=TH260_SetSyncCFD(g_dev,-100,-10); rc<0) pq_throw("SetSyncCFD", rc);
    for(int ch=0; ch<g_ch; ++ch) if(int rc=TH260_SetInputCFD(g_dev,ch,-100,-10); rc<0) pq_throw("SetInputCFD", rc);
  }else{
    if(int rc=TH260_SetSyncEdgeTrg(g_dev,-50,0); rc<0) pq_throw("SetSyncEdgeTrg", rc);
    for(int ch=0; ch<g_ch; ++ch) if(int rc=TH260_SetInputEdgeTrg(g_dev,ch,-50,0); rc<0) pq_throw("SetInputEdgeTrg", rc);
  }
  if(int rc=TH260_SetSyncChannelOffset(g_dev,sync_offset_ps); rc<0) pq_throw("SetSyncChannelOffset", rc);
  for(int ch=0; ch<g_ch; ++ch) if(int rc=TH260_SetInputChannelOffset(g_dev,ch,0); rc<0) pq_throw("SetInputChannelOffset", rc);
  if(int rc=TH260_SetHistoLen(g_dev,MAXLENCODE,&g_len); rc<0) pq_throw("SetHistoLen", rc);
  if(int rc=TH260_SetBinning(g_dev,binning); rc<0) pq_throw("SetBinning", rc);
  if(int rc=TH260_SetOffset(g_dev,offset_ps); rc<0) pq_throw("SetOffset", rc);
  if(int rc=TH260_GetResolution(g_dev,&g_res); rc<0) pq_throw("GetResolution", rc);

  g_hist.assign(g_ch, std::vector<uint32_t>(g_len));
  Sleep(150);
}

static void th260_acquire(int tacq_ms){
  if(int rc=TH260_ClearHistMem(g_dev); rc<0) pq_throw("ClearHistMem", rc);
  if(int rc=TH260_StartMeas(g_dev,tacq_ms); rc<0) pq_throw("StartMeas", rc);
  int ctc=0; do{ if(int rc=TH260_CTCStatus(g_dev,&ctc); rc<0) pq_throw("CTCStatus", rc); if(!ctc) Sleep(10); }while(!ctc);
  if(int rc=TH260_StopMeas(g_dev); rc<0) pq_throw("StopMeas", rc);
  for(int ch=0; ch<g_ch; ++ch) if(int rc=TH260_GetHistogram(g_dev,g_hist[ch].data(),ch,1); rc<0) pq_throw("GetHistogram", rc);
}

int main(){
  std::ios::sync_with_stdio(false);
  std::cout<<"OK ready\n"<<std::flush;
  std::string line;
  try{
    while(std::getline(std::cin,line)){
      if(line.empty()) continue;
      std::istringstream iss(line); std::string cmd; iss>>cmd;
      if(cmd=="exit"||cmd=="quit"){ std::cout<<"OK bye\n"; break; }
      else if(cmd=="init"){ int b=1,o=0,sd=1,so=25000; iss>>b>>o>>sd>>so; th260_init(b,o,sd,so); std::cout<<"OK\n"; }
      else if(cmd=="info"){ std::cout<<"OK RES="<<std::fixed<<std::setprecision(1)<<g_res<<" CH="<<g_ch<<" LEN="<<g_len<<"\n"; }
      else if(cmd=="acquire"){ int ms=5000; iss>>ms; th260_acquire(ms);
        std::vector<uint8_t> raw(size_t(g_ch)*g_len*4);
        uint8_t* p=raw.data(); for(int ch=0; ch<g_ch; ++ch){ memcpy(p,g_hist[ch].data(),size_t(g_len)*4); p+=size_t(g_len)*4; }
        auto b=b64(raw.data(), raw.size());
        std::cout<<"OK HIST CH="<<g_ch<<" LEN="<<g_len<<" BYTES="<<raw.size()<<"\n"<<b<<"\n";
      }
      else if(cmd=="reset"){ th260_init(1,0,1,25000); std::cout<<"OK\n"; }
      else{ std::cout<<"ERR unknown_cmd\n"; }
      std::cout.flush();
    }
  }catch(const std::exception& e){ std::cout<<"ERR "<<e.what()<<"\n"; }
  th260_close();
  return 0;
}
