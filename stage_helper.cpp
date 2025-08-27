// Build: x64 Console, /std:c++17
#include <windows.h>
#include <cstdio>
#include <string>
#include <sstream>
#include <iostream>

extern "C" {
  #include <Thorlabs.MotionControl.TLI.h>
  #include <Thorlabs.MotionControl.KCube.Piezo.h>
}

static char SX[16]={0}, SY[16]={0};
static bool g_open=false;

static void throw_if(bool cond, const char* msg){ if(cond) throw std::runtime_error(msg); }

static void stage_open(const char* sx, const char* sy, int vmax_tenths){
  TLI_BuildDeviceList();
  strncpy_s(SX, sx, 15); strncpy_s(SY, sy, 15);
  throw_if(PCC_Open(SX)<=0, "PCC_Open X");
  throw_if(PCC_Open(SY)<=0, "PCC_Open Y");
  PCC_StartPolling(SX, 200); PCC_StartPolling(SY, 200);
  PCC_Enable(SX); PCC_Enable(SY);
  PCC_SetMaxOutputVoltage(SX, vmax_tenths);
  PCC_SetMaxOutputVoltage(SY, vmax_tenths);
  g_open=true;
}

static void setdac(short vx, short vy){
  throw_if(!g_open, "not_open");
  PCC_SetOutputVoltage(SX, vx);
  PCC_SetOutputVoltage(SY, vy);
}

static void move_ix(int ix,int iy,int w,int h){
  throw_if(!g_open, "not_open");
  // map index [0..w-1] to [0..32767]
  short vx = short((w>1)? (ix*32767/(w-1)) : 0);
  short vy = short((h>1)? (iy*32767/(h-1)) : 0);
  setdac(vx, vy);
}

static void stage_close(){
  if(!g_open) return;
  PCC_StopPolling(SX); PCC_StopPolling(SY);
  PCC_Disable(SX); PCC_Disable(SY);
  PCC_Close(SX); PCC_Close(SY);
  g_open=false;
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
      else if(cmd=="open"){ std::string sx,sy; int vmax=750; iss>>sx>>sy>>vmax; stage_open(sx.c_str(), sy.c_str(), vmax); std::cout<<"OK\n"; }
      else if(cmd=="setdac"){ int vx,vy; iss>>vx>>vy; setdac((short)vx,(short)vy); std::cout<<"OK\n"; }
      else if(cmd=="move_ix"){ int ix,iy,w,h; iss>>ix>>iy>>w>>h; move_ix(ix,iy,w,h); std::cout<<"OK\n"; }
      else if(cmd=="disable"){ stage_close(); std::cout<<"OK\n"; }
      else{ std::cout<<"ERR unknown_cmd\n"; }
      std::cout.flush();
    }
  }catch(const std::exception& e){ std::cout<<"ERR "<<e.what()<<"\n"; }
  stage_close();
  return 0;
}
