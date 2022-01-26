import os
import logging
import threading
import json
import time
import sys
import serial
from flask import Flask, current_app, render_template, request, jsonify, send_from_directory, redirect, Response
import base64
from ipaddress import ip_interface
from datetime import datetime, timedelta
import http.client as httplib
import urllib
from functools import wraps

logging.basicConfig(
    format='%(asctime)s %(levelname)-8s %(message)s',
    #level=logging.INFO,
    level=logging.ERROR,
    datefmt='%Y-%m-%d %H:%M:%S')

#log = logging.getLogger('werkzeug')
#log.setLevel(logging.ERROR)

''' Config file '''
configFile = "pump.cfg"
appCfg = "app.cfg"
''' Sites enabled without password'''
enabledSite = ip_interface('192.168.1.0/24')
''' Serial port '''
baudrate = 19200
port = "ttyUSB0"
timeout = 0.25

def normalize(v, min, max):
    if (v < min): return min
    if (v > max): return max
    return v

def normalizeM(v, min, mid, max):
    if (v < mid): return min
    if (v > max): return max
    return v

class Settings:
    _SETTINGS = {"mode": 0,"p1pw1": 0,"p2pw1": 0,"p3pw1": 0,"p4pw1": 0,"p1pw2": 0,"p2pw2": 0,"p3pw2": 0,"p4pw2": 0,
        "pulsetime": 30,"foodtimer": 15,"moonlight": 0,"stormcycle": 0,"storminterval": 0,"nightmode": 0,"interval": 0,
        "seqtime": 0,"wavecontroller": 0,"waveperiod": 30,"waveinverse": 0,"ramptime": 1,"minflow": 0,"random": 0 }

    @classmethod
    def init(cls, str):
        cls.load(str)

    @classmethod
    def var(cls, str) -> int:
        return cls._SETTINGS[str]

    @classmethod
    def var(cls, k: str, v: int):
        cls._SETTINGS[k] = v

    @classmethod
    def load(cls,str):
        f = str.split(';')
        cls._SETTINGS["mode"] = int(f[0])
        cls._SETTINGS["p1pw1"] = int(f[1])
        cls._SETTINGS["p2pw1"] = int(f[2])
        cls._SETTINGS["p3pw1"] = int(f[3])
        cls._SETTINGS["p4pw1"] = int(f[4])
        cls._SETTINGS["p1pw2"] = int(f[5])
        cls._SETTINGS["p2pw2"] = int(f[6])
        cls._SETTINGS["p3pw2"] = int(f[7])
        cls._SETTINGS["p4pw2"] = int(f[8])
        cls._SETTINGS["pulsetime"] = int(f[9])
        cls._SETTINGS["foodtimer"] = int(f[10])
        cls._SETTINGS["moonlight"] = int(f[11])
        cls._SETTINGS["stormcycle"] = int(f[12])
        cls._SETTINGS["storminterval"] = int(f[13])
        cls._SETTINGS["nightmode"] = int(f[14])
        cls._SETTINGS["interval"] = int(f[15])
        cls._SETTINGS["seqtime"] = int(f[16])
        cls._SETTINGS["wavecontroller"] = int(f[17])
        cls._SETTINGS["waveperiod"] = int(f[18])
        cls._SETTINGS["waveinverse"] = int(f[19])
        cls._SETTINGS["ramptime"] = int(f[20])
        cls._SETTINGS["minflow"] = int(f[21])
        cls._SETTINGS["random"] = int(f[22])        
    
    @classmethod
    def val(cls) -> str:
        return "%i;%i;%i;%i;%i;%i;%i;%i;%i;%i;%i;%i;%i;%i;%i;%i;%i;%i;%i;%i;%i;%i;%i" % \
        (cls._SETTINGS["mode"], cls._SETTINGS["p1pw1"], cls._SETTINGS["p2pw1"], \
        cls._SETTINGS["p3pw1"], cls._SETTINGS["p4pw1"], cls._SETTINGS["p1pw2"], \
        cls._SETTINGS["p2pw2"], cls._SETTINGS["p3pw2"], cls._SETTINGS["p4pw2"], \
        cls._SETTINGS["pulsetime"], cls._SETTINGS["foodtimer"], cls._SETTINGS["moonlight"], \
        cls._SETTINGS["stormcycle"], cls._SETTINGS["storminterval"], cls._SETTINGS["nightmode"], \
        cls._SETTINGS["interval"], cls._SETTINGS["seqtime"], cls._SETTINGS["wavecontroller"], \
        cls._SETTINGS["waveperiod"], cls._SETTINGS["waveinverse"], cls._SETTINGS["ramptime"], \
        cls._SETTINGS["minflow"], cls._SETTINGS["random"])

    @classmethod
    def refresh(cls):
        try:
            cls.var("foodtimer",normalize(int(Config.var("f")),0,15))
            if (Config.var("s") != 0):
                cls.var("stormcycle",1)
                cls.var("storminterval",normalize(int(Config.var("s")),1,191) )
            else:
                cls.var("stormcycle",0)
            cls.var("ramptime",normalize(int(Config.var("r")),0,5))
        except:
            pass

class Config(object):
    _CONFIG = None
    _CFG = None
    _CHANGED = False

    @classmethod
    def init(cls):
        cls.load()

    @staticmethod
    def var(configvar: str) -> str:
        assert Config._CONFIG
        if configvar not in Config._CONFIG:
            raise Exception("Config file error")
        return Config._CONFIG[configvar]
    
    @classmethod
    def load(self):
        try:
            with open(configFile, 'r') as f:
                Config._CONFIG = json.load(f)
        except:
            Config._CONFIG = json.loads('{}')
            sys.exit(1)
        
        try:
            with open(appCfg, 'r') as f:
                Config._CFG = json.load(f)
                print(Config._CFG)
        except:
            Config._CFG = json.loads('{"lastStorm":"00:00"}')

    @classmethod
    def reset(cls) -> None:
        cls._CONFIG = None

    @classmethod
    def refresh(cls) -> None:
        try:
            with open(configFile, 'r') as f:
                cls._CONFIG = json.load(f)
                cls._CHANGED = True
        except:
            cls._CONFIG = json.loads('{}')

    @classmethod
    def saveApp(cls) -> None:
        try:
            with open(appCfg, 'w') as o:
                o.write(json.dumps(cls._CFG))
                o.flush()
        except Exception as e:
            print("App config save error")
            print(e)

    @classmethod
    def changed(cls):
        return cls._CHANGED

    @classmethod
    def accept(cls) -> None:
        cls._CHANGED = False

    @staticmethod
    def appVar(configvar: str) -> str:
        assert Config._CFG
        if configvar not in Config._CFG:
            raise Exception("Config file error")
        return Config._CFG[configvar]

    @staticmethod
    def setAppVar(configvar: str, value: str) -> None:
        assert Config._CFG
        Config._CFG[configvar] = value
        print(Config._CFG[configvar])

class Driver7096():
    baudrate = baudrate
    timeout = timeout
    connected = False
    uart = None
    portname = port
    model = "Disconnected"
    
    def __init__(self):
        self.baudrate = baudrate
        self.timeout = timeout
        self.connected = False
        self.uart = None
        self.portname = port

    @classmethod
    def serGetResponse(self):
        l = self.uart.read(256)
        if l[0] != 0x02:
            raise RuntimeError("Missing start of data!")
        elif l[-2] != 0x03:
            raise RuntimeError("Missing end of data!")
        return(l[1:-2])

    #receive data from unit
    @classmethod
    def serReceive(self):
        # Get model number and firmware version
        self.uart.write(b'\x02?\x03\r')
        r = self.serGetResponse()
        self.model = r.decode('UTF-8')
        print("Found %s" % self.model,flush=True)
        # Get current settings
        self.uart.write(b'\x020data\x03\r')
        r = self.serGetResponse()
        # Convert responce to string and parse it to a settings object
        print("Current settings: %s" % r.decode('UTF-8') ,flush=True)

    @classmethod
    def serDisconnect(self):
        try:
            self.uart.close()
            self.connected = False
        except Exception as e:
            print(e, flush=True)

    @classmethod
    def serConnect(self):
        if self.connected == False:
                try:
                    # Open serial port and do initialization sequence needed to wake up 7096
                    self.uart = serial.Serial(port="/dev/"+self.portname, baudrate=self.baudrate, timeout=self.timeout, rtscts=False, dsrdtr=False)
                    self.uart.setRTS(0)
                    self.uart.setDTR(0)
                    self.uart.setRTS(1)
                    time.sleep(0.1)
                    self.uart.setRTS(0)
                    time.sleep(0.5)
                    self.serReceive()
                    self.connected = True
                except Exception as e:
                    print(e, flush=True)
        else:
            self.ser.close()
            self.connected = False

    @classmethod
    def serSend(self):
        try:
            self.uart.write(b'\x02')
            self.uart.write(Settings.val().encode('ascii'))
            self.uart.write(b'\x03\r')
        except Exception as e:
            print(e, flush=True)

    @classmethod
    def run(self):
        dP = DriverPump()
        dP.start()
        pass

class DriverPump(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.sleepTime = 15
        self.oldTxtMode = None
        try:
            self.nextStorm = datetime.strptime(Config.appVar("lastStorm"),"%Y%d%m %H:%M") + timedelta(hours = int(Config.var("s")))
        except:
            self.nextStorm = datetime.now()
        self.runStorm = False
        self.runFeed = False
        print("nextStorm",self.nextStorm)

    def storm(self):
        print("Storm")
        Driver7096.serConnect()
        time.sleep(0.5)    
        ''' PUMP 1'''    
        Settings.var("p1pw1",100)
        Settings.var("p2pw1",0)
        Settings.var("p3pw1",0)
        Settings.var("p4pw1",0)
        Settings.var("p1pw2",100)
        Settings.var("p2pw2",0)
        Settings.var("p3pw2",0)
        Settings.var("p4pw2",0)
        print("Sending:",Settings.val(),flush=True)
        Driver7096.serSend()
        time.sleep(20)

        ''' PUMP 2'''    
        Settings.var("p1pw1",0)
        Settings.var("p2pw1",100)
        Settings.var("p3pw1",0)
        Settings.var("p4pw1",0)
        Settings.var("p1pw2",0)
        Settings.var("p2pw2",100)
        Settings.var("p3pw2",0)
        Settings.var("p4pw2",0)
        print("Sending:",Settings.val(),flush=True)
        Driver7096.serSend()
        time.sleep(20)

        ''' PUMP 3'''    
        Settings.var("p1pw1",0)
        Settings.var("p2pw1",0)
        Settings.var("p3pw1",100)
        Settings.var("p4pw1",0)
        Settings.var("p1pw2",0)
        Settings.var("p2pw2",0)
        Settings.var("p3pw2",100)
        Settings.var("p4pw2",0)
        print("Sending:",Settings.val(),flush=True)
        Driver7096.serSend()
        time.sleep(20)

        ''' PUMP 4'''    
        Settings.var("p1pw1",0)
        Settings.var("p2pw1",0)
        Settings.var("p3pw1",0)
        Settings.var("p4pw1",100)
        Settings.var("p1pw2",0)
        Settings.var("p2pw2",0)
        Settings.var("p3pw2",0)
        Settings.var("p4pw2",100)
        print("Sending:",Settings.val(),flush=True)
        Driver7096.serSend()
        time.sleep(20)

        ''' PUMP 1+2'''    
        Settings.var("p1pw1",100)
        Settings.var("p2pw1",100)
        Settings.var("p3pw1",0)
        Settings.var("p4pw1",0)
        Settings.var("p1pw2",100)
        Settings.var("p2pw2",100)
        Settings.var("p3pw2",0)
        Settings.var("p4pw2",0)
        print("Sending:",Settings.val(),flush=True)
        Driver7096.serSend()
        time.sleep(20)

        ''' PUMP 3+4'''    
        Settings.var("p1pw1",0)
        Settings.var("p2pw1",0)
        Settings.var("p3pw1",100)
        Settings.var("p4pw1",100)
        Settings.var("p1pw2",0)
        Settings.var("p2pw2",0)
        Settings.var("p3pw2",100)
        Settings.var("p4pw2",100)
        print("Sending:",Settings.val(),flush=True)
        Driver7096.serSend()
        time.sleep(20)

        ''' PUMP 1+3'''    
        Settings.var("p1pw1",100)
        Settings.var("p2pw1",0)
        Settings.var("p3pw1",100)
        Settings.var("p4pw1",0)
        Settings.var("p1pw2",100)
        Settings.var("p2pw2",0)
        Settings.var("p3pw2",100)
        Settings.var("p4pw2",0)
        print("Sending:",Settings.val(),flush=True)
        Driver7096.serSend()
        time.sleep(20)        

        ''' PUMP 2+4'''    
        Settings.var("p1pw1",0)
        Settings.var("p2pw1",100)
        Settings.var("p3pw1",0)
        Settings.var("p4pw1",100)
        Settings.var("p1pw2",0)
        Settings.var("p2pw2",100)
        Settings.var("p3pw2",0)
        Settings.var("p4pw2",100)        
        print("Sending:",Settings.val(),flush=True)
        Driver7096.serSend()
        time.sleep(20)        

        ''' PUMP ALL'''    
        Settings.var("p1pw1",100)
        Settings.var("p2pw1",100)
        Settings.var("p3pw1",100)
        Settings.var("p4pw1",100)
        Settings.var("p1pw2",100)
        Settings.var("p2pw2",100)
        Settings.var("p3pw2",100)
        Settings.var("p4pw2",100)        
        print("Sending:",Settings.val(),flush=True)
        Driver7096.serSend()
        time.sleep(20) 

        ''' PUMP 1+2 30 sec'''    
        Settings.var("p1pw1",100)
        Settings.var("p2pw1",100)
        Settings.var("p3pw1",0)
        Settings.var("p4pw1",0)
        Settings.var("p1pw2",100)
        Settings.var("p2pw2",100)
        Settings.var("p3pw2",0)
        Settings.var("p4pw2",0)
        print("Sending:",Settings.val(),flush=True)
        Driver7096.serSend()
        time.sleep(30)

        ''' PUMP 3+4 30 sec'''    
        Settings.var("p1pw1",0)
        Settings.var("p2pw1",0)
        Settings.var("p3pw1",100)
        Settings.var("p4pw1",100)
        Settings.var("p1pw2",0)
        Settings.var("p2pw2",0)
        Settings.var("p3pw2",100)
        Settings.var("p4pw2",100)
        print("Sending:",Settings.val(),flush=True)
        Driver7096.serSend()
        time.sleep(30)


        ''' PUMP 1 10 sec'''    
        Settings.var("p1pw1",100)
        Settings.var("p2pw1",0)
        Settings.var("p3pw1",0)
        Settings.var("p4pw1",0)
        Settings.var("p1pw2",100)
        Settings.var("p2pw2",0)
        Settings.var("p3pw2",0)
        Settings.var("p4pw2",0)
        print("Sending:",Settings.val(),flush=True)
        Driver7096.serSend()
        time.sleep(10)

        ''' PUMP 2'''    
        Settings.var("p1pw1",0)
        Settings.var("p2pw1",100)
        Settings.var("p3pw1",0)
        Settings.var("p4pw1",0)
        Settings.var("p1pw2",0)
        Settings.var("p2pw2",100)
        Settings.var("p3pw2",0)
        Settings.var("p4pw2",0)
        print("Sending:",Settings.val(),flush=True)
        Driver7096.serSend()
        time.sleep(10)

        ''' PUMP 3'''    
        Settings.var("p1pw1",0)
        Settings.var("p2pw1",0)
        Settings.var("p3pw1",100)
        Settings.var("p4pw1",0)
        Settings.var("p1pw2",0)
        Settings.var("p2pw2",0)
        Settings.var("p3pw2",100)
        Settings.var("p4pw2",0)
        print("Sending:",Settings.val(),flush=True)
        Driver7096.serSend()
        time.sleep(10)

        ''' PUMP 4'''    
        Settings.var("p1pw1",0)
        Settings.var("p2pw1",0)
        Settings.var("p3pw1",0)
        Settings.var("p4pw1",100)
        Settings.var("p1pw2",0)
        Settings.var("p2pw2",0)
        Settings.var("p3pw2",0)
        Settings.var("p4pw2",100)
        print("Sending:",Settings.val(),flush=True)
        Driver7096.serSend()
        time.sleep(10)

        ''' PUMP ALL'''    
        Settings.var("p1pw1",100)
        Settings.var("p2pw1",100)
        Settings.var("p3pw1",100)
        Settings.var("p4pw1",100)
        Settings.var("p1pw2",100)
        Settings.var("p2pw2",100)
        Settings.var("p3pw2",100)
        Settings.var("p4pw2",100)        
        print("Sending:",Settings.val(),flush=True)
        Driver7096.serSend()
        time.sleep(5) 

        Driver7096.serDisconnect()
        time.sleep(0.5)
        print('Storm end')
        self.runStorm = False


    def getMode(self):
        tm = time.localtime()
        mc = int(tm[3]) * 60 + int(tm[4])
        feedTimeSlot = Config.var("ft").split(';')
        feedPause = int(Config.var("f"))
        dnow = datetime.now()
        stormTime = dnow + timedelta(hours = int(Config.var("s")))
        if (dnow >= self.nextStorm):
            self.nextStorm = stormTime
            print(Config.appVar('lastStorm'))
            Config.setAppVar("lastStorm",dnow.strftime("%Y%d%m %H:%M"))
            Config.saveApp()
            self.runStorm = True
        for val in feedTimeSlot:
            d = datetime.strptime(val,'%H:%M')
            d1 = d + timedelta(minutes=feedPause)
            if dnow.time() > d.time() and  dnow.time() < d1.time():
                Settings.var("p1pw1",0)
                Settings.var("p2pw1",0)
                Settings.var("p3pw1",0)
                Settings.var("p4pw1",0)
                Settings.var("p1pw2",0)
                Settings.var("p2pw2",0)
                Settings.var("p3pw2",0)
                Settings.var("p4pw2",0)
                return 'Feed'

        if (self.runStorm):
            return 'Storm'

        for data in Config.var("d"):
            arData = data.split(";")
            start = arData[1]
            hs,ms = start.split(":")
            end = arData[2]
            he,me = end.split(":")
            mStart = int(hs)*60+int(ms)
            mEnd = int(he)*60+int(me)
            if (mc > mStart and mc <= mEnd):
                Settings.var("mode",normalize(int(arData[3]),0,2))
                Settings.var("interval",normalize(int(arData[4]),1,779))
                Settings.var("seqtime",normalize(int(arData[5]),1,10))
                Settings.var("p1pw1",normalizeM(int(arData[6]),0,30,100))
                Settings.var("p2pw1",normalizeM(int(arData[7]),0,30,100))
                Settings.var("p3pw1",normalizeM(int(arData[8]),0,30,100))
                Settings.var("p4pw1",normalizeM(int(arData[9]),0,30,100))
                Settings.var("p1pw2",normalizeM(int(arData[10]),0,30,100))
                Settings.var("p2pw2",normalizeM(int(arData[11]),0,30,100))
                Settings.var("p3pw2",normalizeM(int(arData[12]),0,30,100))
                Settings.var("p4pw2",normalizeM(int(arData[13]),0,30,100))
                Settings.var("pulsetime",normalize(int(arData[14]),30,800))
                Settings.var("random",normalize(int(arData[15]),0,1))
                ''' return mode name '''
                if (Config.changed()):
                    Config.accept()
                    self.oldTxtMode = self.oldTxtMode + dnow.strftime("%y%d%m%H%M%S")
                return arData[0]
        return 'Undef'

    def run(self):
        while True:
            try:
                txtMode = self.getMode()
                if (self.oldTxtMode != txtMode):
                    print(txtMode, flush=True)
                    self.oldTxtMode = txtMode
                    if (txtMode == "Storm"):
                        self.storm()
                    elif (txtMode != "Undef"):
                        ''' Send program to 7096'''
                        Driver7096.serConnect()
                        time.sleep(0.5)
                        print("Sending:",Settings.val(),flush=True)
                        Driver7096.serSend()
                        time.sleep(0.5)
                        Driver7096.serDisconnect()
                        time.sleep(0.5)
                    else:
                        pass
            except Exception as e:
                print(e,flush=True)
                break

            time.sleep(self.sleepTime)

def getIP():
   if 'X-Real-Ip' in request.headers:
      return ip_interface(request.headers.getlist("X-Real-Ip")[0])
   else:
      return ip_interface(request.remote_addr)

def check(authorization_header):
    username = b"lsl:reef"
    incip = getIP()
    if incip.network.overlaps(enabledSite.network):
       return True
    enc_user = base64.b64encode(username).decode("utf-8")
    inc_uname_pass = authorization_header.split()[-1]       
    if inc_uname_pass == enc_user:
        return True

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        authorization_header = request.headers.get('Authorization')
        if authorization_header and check(authorization_header):
            return f(*args, **kwargs)
        else:
            incip = getIP()
            if incip.network.overlaps(enabledSite.network):
               return f(*args, **kwargs)
            else:
               resp = Response()
               resp.headers['WWW-Authenticate'] = 'Basic'
               return resp, 401
        return f(*args, **kwargs)
    return decorated

def main():
    web = Flask(__name__)

    @web.route("/getData",  methods = ['GET'])
    def getData():
        return send_from_directory('.', configFile)

    @web.route("/saveData",  methods = ['POST'])
    @login_required
    def saveData():
        try:
            content = request.json
            with open(configFile, 'w') as o:
                o.write(json.dumps(content))
                o.flush()
                Config.refresh()
                Settings.refresh()
                return jsonify({"status":"OK"})
        except Exception as e:
            print(e, flush=True)
            return jsonify({"status":"ERROR"})
            
    @web.route("/favicon.ico",  methods = ['GET'])
    def favicon():
         return send_from_directory(os.path.join(current_app.root_path, 'static'),
            'favicon.ico', mimetype='image/vnd.microsoft.icon')

    @web.route("/",  methods = ['GET'])
    def index():
        return send_from_directory('html', 'index.html')

    @web.route('/html/<path:path>')
    def send_static(path):
        return send_from_directory('html', path)

    @web.route("/login",  methods = ['GET'])
    @login_required
    def login():
        return jsonify({"status":"OK"})

    @web.route("/version",  methods = ['GET'])
    def version():
        return jsonify({"version":Driver7096.model})        

    Config.init()
    Settings.init("0;0;0;0;0;0;0;0;0;30;15;0;0;0;0;0;0;0;30;0;1;0;0")
    Settings.refresh()
    try:
        print("Test connection",flush=True)
        Driver7096.serConnect()
        time.sleep(0.5)
        Driver7096.serDisconnect()
        print("Connection OK",flush=True)
    except Exception as e:
        print(e,flush=True)
        sys.exit(1)

    Driver7096.run()

    from waitress import serve
    serve(web, host="0.0.0.0", port=8080)
    #web.run(host='0.0.0.0', port=8080, debug=True)
    
if __name__ == '__main__':
   try:
      main()
   except KeyboardInterrupt:
      sys.exit(1)
