# ml_weather.py
import json
import os
from datetime import datetime, timedelta
import pandas as pd
# import numpy as np # Можливо, не потрібен тут напряму
from neuralprophet import NeuralProphet

TRAINED_NP_MODELS_CACHE = {}
LOGS_DIR_ML = "logs" 
MODEL_DATA_FREQUENCY = "H" # !!! ВАЖЛИВО: Налаштуйте цю частоту !!!

def set_logs_dir(logs_directory):
    global LOGS_DIR_ML
    LOGS_DIR_ML = logs_directory

def _clear_one_model_from_cache(model_key):
    if model_key in TRAINED_NP_MODELS_CACHE:
        print(f"🗑️ [ML CACHE] Видалення моделі {model_key} з кешу.")
        if TRAINED_NP_MODELS_CACHE.get(model_key) is not None:
            del TRAINED_NP_MODELS_CACHE[model_key]

def clear_models_for_mac_from_cache(mac_address_prefix):
    keys_to_delete = [key for key in TRAINED_NP_MODELS_CACHE if key.startswith(mac_address_prefix)]
    for key in keys_to_delete:
        print(f"🗑️ [ML CACHE] Видалення моделі {key} для MAC {mac_address_prefix} з кешу.")
        if key in TRAINED_NP_MODELS_CACHE: # Додаткова перевірка перед видаленням
            del TRAINED_NP_MODELS_CACHE[key]
    if not keys_to_delete:
        pass # Можна не виводити повідомлення, якщо нічого не знайдено, щоб не засмічувати лог
        # print(f"ℹ️ [ML CACHE] Моделі для MAC {mac_address_prefix} не знайдені для видалення.")

def model_exists_in_cache(model_key): # <--- ДОДАНА ФУНКЦІЯ
    """Перевіряє, чи існує модель в кеші і чи вона не None."""
    return model_key in TRAINED_NP_MODELS_CACHE and TRAINED_NP_MODELS_CACHE[model_key] is not None

def get_trained_model_from_cache(model_key):
    """Повертає навчену модель з кешу, якщо вона існує, інакше None."""
    return TRAINED_NP_MODELS_CACHE.get(model_key, None)

def get_historical_data_for_model(mac_address, target_sensor_id, regressor_config=None, N_days=90):
    if regressor_config is None: regressor_config = {}
    log_filename_mac = mac_address.replace(":", "").lower()
    log_path = os.path.join(LOGS_DIR_ML, f"{log_filename_mac}.log")
    data_points = []
    if not os.path.exists(log_path):
        # print(f"⚠️ [ML GET DATA] Лог-файл не знайдено: {log_path}")
        return pd.DataFrame()
    try:
        with open(log_path, "r", encoding="utf-8") as log_file:
            for line in log_file:
                try:
                    log_entry = json.loads(line)
                    timestamp_str, entry_data = log_entry.get("timestamp"), log_entry.get("data", {})
                    if timestamp_str:
                        dt_object = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                        current_point = {"ds": dt_object}
                        target_val_raw, target_val = entry_data.get(target_sensor_id), None
                        if isinstance(target_val_raw, (int, float)): target_val = float(target_val_raw)
                        elif isinstance(target_val_raw, str):
                            try: target_val = float(target_val_raw)
                            except ValueError: pass
                        if target_val is None: continue
                        current_point['y'] = target_val
                        for model_reg_name, actual_sens_id in regressor_config.items():
                            reg_val_raw, reg_val = entry_data.get(actual_sens_id), None
                            if isinstance(reg_val_raw, (int, float)): reg_val = float(reg_val_raw)
                            elif isinstance(reg_val_raw, str):
                                try: reg_val = float(reg_val_raw)
                                except ValueError: pass
                            current_point[model_reg_name] = reg_val
                        data_points.append(current_point)
                except (json.JSONDecodeError, ValueError): continue
    except IOError: return pd.DataFrame()
    if not data_points: return pd.DataFrame()
    df = pd.DataFrame(data_points)
    if df.empty: return pd.DataFrame()

    try:
        df['ds'] = pd.to_datetime(df['ds'])
        df = df.sort_values(by="ds").drop_duplicates(subset=['ds'], keep='last').set_index('ds')
    except Exception as e_df_prep:
        print(f"Error during initial df prep for {mac_address}-{target_sensor_id}: {e_df_prep}")
        return pd.DataFrame()


    resampled_data = {}
    if 'y' in df.columns: 
        if not df['y'].dropna().empty: # Перевіряємо чи є не-NaN значення перед ресемплінгом
            resampled_data['y'] = df['y'].resample(MODEL_DATA_FREQUENCY).mean()
        else: # Якщо всі значення NaN, ресемплінг дасть всі NaN
            resampled_data['y'] = pd.Series(index=df.resample(MODEL_DATA_FREQUENCY).asfreq().index, dtype=float)

    else: return pd.DataFrame()

    for model_reg_name in regressor_config.keys():
        if model_reg_name in df.columns:
            if not df[model_reg_name].dropna().empty:
                resampled_data[model_reg_name] = df[model_reg_name].resample(MODEL_DATA_FREQUENCY).mean()
            else:
                resampled_data[model_reg_name] = pd.Series(index=df.resample(MODEL_DATA_FREQUENCY).asfreq().index, dtype=float)


    final_df = pd.DataFrame(resampled_data).reset_index()
    
    if not final_df.empty:
        cutoff_date = datetime.now() - timedelta(days=N_days)
        final_df = final_df[final_df['ds'] >= cutoff_date]

    if 'y' in final_df.columns:
        final_df['y'] = final_df['y'].ffill().bfill()
        if final_df['y'].isnull().all(): return pd.DataFrame()
    else: # Якщо 'y' немає після всього, це проблема
        return pd.DataFrame() 
    
    for model_reg_name in regressor_config.keys():
        if model_reg_name in final_df.columns:
            final_df[model_reg_name] = final_df[model_reg_name].ffill().bfill()
            if final_df[model_reg_name].isnull().any():
                 mean_val = final_df[model_reg_name].mean()
                 final_df[model_reg_name] = final_df[model_reg_name].fillna(mean_val if not pd.isna(mean_val) else 0)
        else: final_df[model_reg_name] = 0
    # print(f"[ML GET DATA] Дані для {mac_address}-{target_sensor_id} (рес. до {MODEL_DATA_FREQUENCY}): {len(final_df)} точок")
    return final_df

def train_model(historical_data_df, model_key, regressor_names=None, epochs=30):
    if regressor_names is None: regressor_names = []
    print(f"[ML TRAIN] {model_key}, регресори: {regressor_names}, даних: {len(historical_data_df) if historical_data_df is not None else 'None'}, епох: {epochs}, freq: {MODEL_DATA_FREQUENCY}")
    
    if historical_data_df is None or historical_data_df.empty or len(historical_data_df) < 25:
        print(f"⚠️ [ML TRAIN] Мало даних ({len(historical_data_df) if historical_data_df is not None else 0}) для {model_key}.")
        _clear_one_model_from_cache(model_key); return None
        
    for reg_name in regressor_names:
        if reg_name not in historical_data_df.columns:
            print(f"⚠️ [ML TRAIN] Регресор '{reg_name}' не знайдено в даних для {model_key}.")
            return None
            
    try:
        model_np = NeuralProphet( n_lags=5, yearly_seasonality=False, weekly_seasonality="auto", 
                                 daily_seasonality="auto", epochs=epochs)
        for reg_name in regressor_names: model_np.add_regressor(name=reg_name, mode="additive")
        
        # Переконуємося, що ds має правильний тип перед fit
        if 'ds' in historical_data_df.columns and not pd.api.types.is_datetime64_any_dtype(historical_data_df['ds']):
            historical_data_df['ds'] = pd.to_datetime(historical_data_df['ds'])

        model_np.fit(historical_data_df, freq=MODEL_DATA_FREQUENCY, progress="bar")
        TRAINED_NP_MODELS_CACHE[model_key] = model_np
        print(f"✅ [ML TRAIN] Модель {model_key} (пере)навчена.")
        return model_np
    except Exception as e: 
        print(f"❌ [ML TRAIN] Помилка тренування {model_key}: {e}")
        _clear_one_model_from_cache(model_key); return None

def make_prediction(model_key, future_df_with_regressors):
    if not model_exists_in_cache(model_key):
        print(f"🔎 [ML PREDICT] Модель {model_key} не знайдена в кеші.")
        return None
    model_np = get_trained_model_from_cache(model_key)
    if model_np is None: return None

    if future_df_with_regressors is None or future_df_with_regressors.empty:
        print(f"🔎 [ML PREDICT] Немає майбутніх даних регресорів для {model_key}.")
        return None
    
    expected_regressors = model_np.regressors.keys() if model_np.regressors else []
    for reg_name in expected_regressors:
        if reg_name not in future_df_with_regressors.columns:
            print(f"⚠️ [ML PREDICT] Регресор '{reg_name}' відсутній в future_df для {model_key}. Додано з 0.")
            future_df_with_regressors[reg_name] = 0 
    try:
        if 'ds' in future_df_with_regressors.columns and not pd.api.types.is_datetime64_any_dtype(future_df_with_regressors['ds']):
            future_df_with_regressors['ds'] = pd.to_datetime(future_df_with_regressors['ds'])
        
        # Перевірка, чи є df_historic в моделі
        if model_np.df_historic is None or model_np.df_historic.empty:
            print(f"⚠️ [ML PREDICT] df_historic в моделі {model_key} порожній. Прогноз неможливий.")
            return None

        df_future_dates = model_np.make_future_dataframe(
            df=model_np.df_historic, periods=len(future_df_with_regressors), 
            n_historic_predictions=0, freq=MODEL_DATA_FREQUENCY
        )
        if not pd.api.types.is_datetime64_any_dtype(df_future_dates['ds']):
            df_future_dates['ds'] = pd.to_datetime(df_future_dates['ds'])
            
        final_future_df = pd.merge(df_future_dates[['ds']], future_df_with_regressors, on='ds', how='left')
        for reg_name in expected_regressors:
            if reg_name in final_future_df.columns and final_future_df[reg_name].isnull().any():
                final_future_df[reg_name] = final_future_df[reg_name].ffill().bfill().fillna(0)
        
        if final_future_df.empty or 'ds' not in final_future_df.columns: return None
        
        forecast_df = model_np.predict(final_future_df)
        
        if forecast_df is not None and not forecast_df.empty and 'yhat1' in forecast_df.columns and 'ds' in forecast_df.columns:
            return forecast_df[['ds', 'yhat1']] 
        return None
    except Exception as e: 
        print(f"❌ [ML PREDICT] Помилка прогнозування {model_key}: {e}"); return None

def generate_future_regressor_pattern(start_time, periods, model_regressor_name="light_level", 
                                      day_hr_start=6, day_hr_end=20, val_day=800, val_night=50):
    future_dates = pd.date_range(start=start_time, periods=periods, freq=MODEL_DATA_FREQUENCY)
    reg_values = [val_day if day_hr_start <= dt.hour < day_hr_end else val_night for dt in future_dates]
    return pd.DataFrame({'ds': future_dates, model_regressor_name: reg_values})
