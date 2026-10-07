-- EdgeTX Function Script. Copy to /SCRIPTS/FUNCTIONS/DDSTK.lua.
-- Prototype: verify USB-VCP=LUA on the target Pocket before flying with it.
-- Reads values only. Does not change model outputs or ELRS settings.
local RAW_STICKS = true -- false = mixer outputs according to mapping below
local CHANNELS = { roll="ch1", pitch="ch2", yaw="ch4", throttle="ch3",
                   arm="ch5", crash="ch8" }
local STICKS = { roll="ail", pitch="ele", yaw="rud", throttle="thr" }
-- Sensors to forward, by the names EdgeTX shows on its Telemetry page (use "Discover new sensors" there first).
-- Names the radio does not know are skipped. Text sensors (flight mode) cannot be sent.
local TELEMETRY = { "RQly", "RSNR", "1RSS", "2RSS", "TPWR", "RFMD", "ANT", "TRSS", "TQly", "TSNR", -- link
                    "RxBt", "Curr", "Capa", "Bat%",                                               -- battery
                    "Sats", "GSpd", "GAlt", "Alt", "VSpd", "Hdg",                                 -- GPS, altitude
                    "Ptch", "Roll", "Yaw" }                                                       -- attitude
local TELEMETRY_BATCH = 2 -- sensors sent per call (round robin), so a call never sends a long burst
local SAMPLE_TICKS = 3 -- minimum interval, callbacks are not deterministic
local TELEMETRY_TICKS = 5
local GPS_TICKS = 50
local OUTPUT_TICKS = 10 -- one half (8 channels) per interval, alternating, for the setup/learn screen
local ARM_THRESHOLD = 0
local CRASH_THRESHOLD = 0
local seq, lastSample, lastTelemetry, lastOutputs, lastGps = 0, -100, -100, -100, -100
local sources, sensors, outputs = {}, {}, {}
local outputsOk, outHalf, initNote, lookupNote = true, 0, nil, nil
local telemetryOk, telIndex, gpsId = true, 0, nil
local lastArm, lastCrash, valid = nil, nil, false
local helloSent = false

local function resolve(name)
  local info = getFieldInfo(name)
  if info then return info.id end
  -- Display names (e.g. CH1) differ from API field names (e.g. ch1).
  if getSourceIndex then
    local index = getSourceIndex(name)
    if index and index > 0 then return index end
  end
  return nil
end

local function read(id)
  if not id then return nil end
  if getSourceValue then return getSourceValue(id) end
  return getValue(id)
end

local function send(line)
  if serialWrite then serialWrite(line .. "\n") end
end

local function nextSeq()
  seq = (seq + 1) % 65536
  return seq
end

local function init()
  local axes = RAW_STICKS and STICKS or CHANNELS
  sources.roll = resolve(axes.roll)
  sources.pitch = resolve(axes.pitch)
  sources.yaw = resolve(axes.yaw)
  sources.throttle = resolve(axes.throttle)
  sources.arm = resolve(CHANNELS.arm)
  sources.crash = resolve(CHANNELS.crash)
  valid = sources.roll and sources.pitch and sources.yaw and sources.throttle
          and sources.arm and sources.crash
  -- The sensors that exist on this radio; the rest are skipped. A failing lookup skips that sensor only.
  local badLookup = nil
  for _, name in ipairs(TELEMETRY) do
    local ok, id = pcall(resolve, name)
    if not ok then badLookup = name .. " " .. tostring(id)
    elseif id then sensors[#sensors + 1] = { name = name, id = id } end
  end
  local okGps, gps = pcall(resolve, "GPS")
  if okGps then gpsId = gps end
  -- Optional extra: a failure here must never stop the stick stream; the reason is reported instead.
  local resolved = 0
  for i = 1, 16 do
    local ok, id = pcall(resolve, "ch" .. i)
    if not ok then
      outputsOk = false
      initNote = "resolve ch" .. i .. " " .. tostring(id)
      break
    end
    outputs[i] = id or false
    if id then resolved = resolved + 1 end
  end
  if outputsOk then initNote = "channels resolved " .. resolved end
  initNote = initNote .. " sensors " .. #sensors .. (gpsId and " gps" or "")
  if badLookup then lookupNote = "lookup " .. badLookup end  -- sent after the hello, which clears older notes
end

local function event(now, name, value)
  send("E,"..now..","..nextSeq()..","..name..","..value)
end

-- D,tick,seq,text: one-line diagnostics for the host (never required for the overlay).
local function note(text)
  local clean = string.gsub(tostring(text), "^.*DDSTK%.lua", "L")  -- drop the long path prefix
  clean = string.gsub(clean, "[^%w%._: -]", "_")
  send("D,"..getTime()..","..nextSeq()..","..string.sub(clean, 1, 60))
end

-- C,tick,seq,first,v1..v8: channels first..first+7 (first = 1 or 9). Short lines, like S.
local sentOut = {} -- last value sent for each channel, to notice a switch flipping between the periodic sends

local function sendHalf(now, half)
  local first = half * 8 + 1
  local line = "C,"..now..","..nextSeq()..","..first
  for i = 1, 8 do
    local id = outputs[first + i - 1]
    local v = id and read(id)
    local n = type(v) == "number" and math.floor(v) or 0
    sentOut[first + i - 1] = n
    line = line..","..n
  end
  send(line)
end

local function sendOutputs(now)
  outHalf = 1 - outHalf
  sendHalf(now, outHalf)
end

-- A tap on a switch is over in 100 ms, but each half of the channels only goes out every 200 ms: send the half
-- at once when an AUX channel (5..16) moved a long way since it was last sent. Costs a read of 12 channels.
local function watchSwitches(now)
  local flush = { false, false }
  for i = 5, 16 do
    local id = outputs[i]
    local v = id and read(id)
    if type(v) == "number" and sentOut[i] and math.abs(v - sentOut[i]) >= 500 then flush[i <= 8 and 1 or 2] = true end
  end
  for half = 0, 1 do
    if flush[half + 1] then sendHalf(now, half) end
  end
end

-- Fixed-precision number text (shorter than the default 14 digits); falls back to plain concatenation.
local function fmt(value, digits)
  local ok, text = pcall(string.format, "%." .. digits .. "f", value)
  if ok then return text end
  return tostring(value)
end

-- T,tick,seq,sensor,value,current,fresh: TELEMETRY_BATCH sensors per call, round robin.
-- A sensor that raises an error is skipped from then on (and reported); the others carry on.
local function sendTelemetry(now)
  local sent, tries = 0, 0
  while sent < TELEMETRY_BATCH and tries < #sensors do
    tries = tries + 1
    telIndex = telIndex % #sensors + 1
    local sensor = sensors[telIndex]
    if not sensor.bad then
      local ok, value, current, fresh = pcall(getSourceValue, sensor.id)
      if not ok then
        sensor.bad = true
        pcall(note, "sensor "..sensor.name.." "..tostring(value))
      elseif type(value) == "number" then
        send("T,"..now..","..nextSeq()..","..sensor.name..","..fmt(value, 3)..","..(current and 1 or 0)..","..(fresh and 1 or 0))
        sent = sent + 1
      else
        send("T,"..now..","..nextSeq()..","..sensor.name..",0,0,0")  -- lost: explicitly age it out
        sent = sent + 1
      end
    end
  end
end

-- G,tick,seq,lat,lon,plat,plon: EdgeTX returns the GPS sensor as a table (positive = north / east).
local function sendGps(now)
  local v = getValue(gpsId)
  if type(v) ~= "table" or type(v.lat) ~= "number" or type(v.lon) ~= "number" then return end
  local plat, plon = v["pilot-lat"], v["pilot-lon"]
  send("G,"..now..","..nextSeq()..","..fmt(v.lat, 6)..","..fmt(v.lon, 6)..","
       ..fmt(type(plat) == "number" and plat or 0, 6)..","..fmt(type(plon) == "number" and plon or 0, 6))
end

local function run()
  if not valid or not serialWrite then return end -- missing mapping: no false zero data
  local now = getTime()
  if not helloSent then
    send("H,1,"..(RAW_STICKS and "DDRAW" or "DDOUT")..","..now)
    helloSent = true
  end
  if initNote then pcall(note, initNote); initNote = nil end
  if lookupNote then pcall(note, lookupNote); lookupNote = nil end
  if now - lastSample >= SAMPLE_TICKS or now < lastSample then
    lastSample = now
    local r, p, y, t = read(sources.roll), read(sources.pitch), read(sources.yaw), read(sources.throttle)
    local a, c = read(sources.arm), read(sources.crash)
    if type(r)=="number" and type(p)=="number" and type(y)=="number"
       and type(t)=="number" and type(a)=="number" and type(c)=="number" then
      -- Values normally lie in -1024..1024; extended channel limits are possible.
      send("S,"..now..","..nextSeq()..","..math.floor(r)..","..math.floor(p)..","..
           math.floor(y)..","..math.floor(t)..","..math.floor(a)..","..math.floor(c))
      local arm = a > ARM_THRESHOLD and 1 or 0
      local crash = c > CRASH_THRESHOLD and 1 or 0
      if lastArm ~= nil and arm ~= lastArm then event(now,"ARM",arm) end
      if lastCrash ~= nil and crash ~= lastCrash then event(now,"CRASH",crash) end
      lastArm, lastCrash = arm, crash
    end
    if outputsOk then
      local ok, err = pcall(watchSwitches, now)
      if not ok then outputsOk = false; pcall(note, "send "..tostring(err)) end
    end
  end
  if outputsOk and (now - lastOutputs >= OUTPUT_TICKS or now < lastOutputs) then
    lastOutputs = now
    local ok, err = pcall(sendOutputs, now)
    if not ok then outputsOk = false; pcall(note, "send "..tostring(err)) end
  end
  if telemetryOk and getSourceValue and (now - lastTelemetry >= TELEMETRY_TICKS or now < lastTelemetry) then
    lastTelemetry = now
    local ok, err = pcall(sendTelemetry, now)
    if not ok then telemetryOk = false; pcall(note, "telemetry "..tostring(err)) end
  end
  if gpsId and (now - lastGps >= GPS_TICKS or now < lastGps) then
    lastGps = now
    local ok, err = pcall(sendGps, now)
    if not ok then gpsId = nil; pcall(note, "gps "..tostring(err)) end
  end
end

local function background() end -- OFF means no transmission
return { init=init, run=run, background=background }
