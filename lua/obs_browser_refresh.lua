obs = obslua

source_name = "contador-mortes"
interval_seconds = 30

function script_description()
    return "Atualiza automaticamente uma Browser Source no OBS usando cache-buster na URL."
end

function script_defaults(settings)
    obs.obs_data_set_default_string(settings, "source_name", "contador-mortes")
    obs.obs_data_set_default_int(settings, "interval_seconds", 30)
end

function script_properties()
    local props = obs.obs_properties_create()

    obs.obs_properties_add_text(
        props,
        "source_name",
        "Nome da Browser Source",
        obs.OBS_TEXT_DEFAULT
    )

    obs.obs_properties_add_int(
        props,
        "interval_seconds",
        "Intervalo (segundos)",
        5,
        3600,
        1
    )

    return props
end

local function upsert_cache_buster(url, key, value)
    local base, query = string.match(url, "^([^?]*)%??(.*)$")
    if not base then
        return url
    end

    local parts = {}
    local found = false

    if query and query ~= "" then
        for pair in string.gmatch(query, "[^&]+") do
            local k, v = string.match(pair, "^([^=]+)=?(.*)$")
            if k == key then
                v = tostring(value)
                found = true
            end
            table.insert(parts, tostring(k) .. "=" .. tostring(v))
        end
    end

    if not found then
        table.insert(parts, key .. "=" .. tostring(value))
    end

    if #parts == 0 then
        return base
    end

    return base .. "?" .. table.concat(parts, "&")
end

local function refresh_browser_source()
    if source_name == nil or source_name == "" then
        obs.script_log(obs.LOG_WARNING, "Defina o nome da Browser Source no script.")
        return
    end

    local source = obs.obs_get_source_by_name(source_name)
    if source == nil then
        obs.script_log(obs.LOG_WARNING, "Source nao encontrada: " .. source_name)
        return
    end

    local settings = obs.obs_source_get_settings(source)
    if settings == nil then
        obs.obs_source_release(source)
        return
    end

    local url = obs.obs_data_get_string(settings, "url")
    if url == nil or url == "" then
        obs.script_log(obs.LOG_WARNING, "A source nao possui URL. Configure como Browser Source por URL.")
        obs.obs_data_release(settings)
        obs.obs_source_release(source)
        return
    end

    local updated_url = upsert_cache_buster(url, "_obs_refresh", os.time())
    obs.obs_data_set_string(settings, "url", updated_url)
    obs.obs_source_update(source, settings)

    obs.obs_data_release(settings)
    obs.obs_source_release(source)
end

function script_update(settings)
    source_name = obs.obs_data_get_string(settings, "source_name")
    interval_seconds = obs.obs_data_get_int(settings, "interval_seconds")

    obs.timer_remove(refresh_browser_source)

    if interval_seconds < 5 then
        interval_seconds = 5
    end

    obs.timer_add(refresh_browser_source, interval_seconds * 1000)
end

function script_unload()
    obs.timer_remove(refresh_browser_source)
end
