-- EdgeTX Function Script. Copy to /SCRIPTS/FUNCTIONS/DDSTK.lua.
-- Prototype: verify USB-VCP=LUA on the target Pocket before flying with it.
-- Reads values only. Does not change model outputs or ELRS settings.
local RAW_STICKS = true -- false = mixer outputs according to mapping below
local CHANNELS = { roll="ch1", pitch="ch2", yaw="ch4", throttle="ch3",
                   arm="ch5", crash="ch8" }
local STICKS = { roll="ail", pitch="ele", yaw="rud", throttle="thr" }
local TELEMETRY = { "RQly", "RxBt" } -- use actual discovered sensor names
local SAMPLE_TICKS = 3 -- minimum interval, callbacks are not deterministic
local TELEMETRY_TICKS = 20
local OUTPUT_TICKS = 10 -- one half (8 channels) per interval, alternating, for the setup/learn screen
local ARM_THRESHOLD = 0
local CRASH_THRESHOLD = 0
local seq, lastSample, lastTelemetry, lastOutputs = 0, -100, -100, -100
local sources, sensors, outputs = {}, {}, {}
local outputsOk, outHalf, initNote = true, 0, nil
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
  for i, name in ipairs(TELEMETRY) do sensors[i] = resolve(name) or false end
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
local function sendOutputs(now)
  outHalf = 1 - outHalf
  local first = outHalf * 8 + 1
  local line = "C,"..now..","..nextSeq()..","..first
  for i = 1, 8 do
    local id = outputs[first + i - 1]
    local v = id and read(id)
    line = line..","..(type(v) == "number" and math.floor(v) or 0)
  end
  send(line)
end

local function run()
  if not valid or not serialWrite then return end -- missing mapping: no false zero data
  local now = getTime()
  if not helloSent then
    send("H,1,"..(RAW_STICKS and "DDRAW" or "DDOUT")..","..now)
    helloSent = true
  end
  if initNote then pcall(note, initNote); initNote = nil end
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
  end
  if outputsOk and (now - lastOutputs >= OUTPUT_TICKS or now < lastOutputs) then
    lastOutputs = now
    local ok, err = pcall(sendOutputs, now)
    if not ok then outputsOk = false; pcall(note, "send "..tostring(err)) end
  end
  -- Send current=false as well as fresh values: explicitly age out lost telemetry.
  if getSourceValue and (now-lastTelemetry >= TELEMETRY_TICKS or now < lastTelemetry) then
    lastTelemetry = now
    for i, name in ipairs(TELEMETRY) do
      if sensors[i] then
        local value, current, fresh = getSourceValue(sensors[i])
        if type(value)=="number" then
          send("T,"..now..","..nextSeq()..","..name..","..value..","..
               (current and 1 or 0)..","..(fresh and 1 or 0))
        else
          send("T,"..now..","..nextSeq()..","..name..",0,0,0")
        end
      end
    end
  end
end

local function background() end -- OFF means no transmission
return { init=init, run=run, background=background }
