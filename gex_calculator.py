import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import norm
from datetime import datetime
import os

def black_scholes_gamma(S, K, T, r, sigma):
    """
    計算 Black-Scholes Gamma
    """
    if T <= 0 or sigma <= 0:
        return 0
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
    return gamma

def get_option_chain_data(ticker_symbol):
    """
    獲取完整的選擇權鏈數據
    """
    ticker = yf.Ticker(ticker_symbol)
    expirations = ticker.options
    
    history = ticker.history(period="1d")
    if history.empty:
        raise ValueError(f"Could not get price for {ticker_symbol}")
    spot_price = history['Close'].iloc[-1]
    
    all_calls = []
    all_puts = []
    
    today = datetime.now()
    
    for exp in expirations:
        try:
            opt = ticker.option_chain(exp)
            exp_date = datetime.strptime(exp, '%Y-%m-%d')
            T = (exp_date - today).days / 365.0
            if T <= 0: T = 1/365.0
            
            calls = opt.calls.copy()
            puts = opt.puts.copy()
            
            calls.loc[:, 'T'] = T
            puts.loc[:, 'T'] = T
            all_calls.append(calls)
            all_puts.append(puts)
        except Exception as e:
            print(f"Warning: Could not fetch data for expiration {exp}: {e}")
            continue
        
    df_calls = pd.concat(all_calls).reset_index(drop=True)
    df_puts = pd.concat(all_puts).reset_index(drop=True)
    
    return spot_price, df_calls, df_puts

def calculate_gex_and_levels(spot_price, df_calls, df_puts, r=0.04):
    """
    計算 GEX 並尋找 ZGL, Put Wall, Call Wall
    """
    # 修正 SettingWithCopyWarning: 使用 .copy() 並確保數據乾淨
    df_calls = df_calls.dropna(subset=['impliedVolatility', 'openInterest']).copy()
    df_puts = df_puts.dropna(subset=['impliedVolatility', 'openInterest']).copy()
    
    # 計算 Gamma
    df_calls.loc[:, 'gamma'] = df_calls.apply(lambda row: black_scholes_gamma(spot_price, row['strike'], row['T'], r, row['impliedVolatility']), axis=1)
    df_puts.loc[:, 'gamma'] = df_puts.apply(lambda row: black_scholes_gamma(spot_price, row['strike'], row['T'], r, row['impliedVolatility']), axis=1)
    
    # 計算 GEX
    df_calls.loc[:, 'GEX'] = df_calls['gamma'] * df_calls['openInterest'] * 100 * spot_price * spot_price * 0.01
    df_puts.loc[:, 'GEX'] = df_puts['gamma'] * df_puts['openInterest'] * 100 * spot_price * spot_price * 0.01 * -1
    
    # Walls
    put_wall = df_puts.groupby('strike')['openInterest'].sum().idxmax()
    call_wall = df_calls.groupby('strike')['openInterest'].sum().idxmax()
    
    # ZGL (Gamma Flip)
    strikes = np.linspace(spot_price * 0.9, spot_price * 1.1, 50)
    total_gammas = []
    
    df_c_filt = df_calls[df_calls['openInterest'] > 0].copy()
    df_p_filt = df_puts[df_puts['openInterest'] > 0].copy()

    for s in strikes:
        g_calls = df_c_filt.apply(lambda row: black_scholes_gamma(s, row['strike'], row['T'], r, row['impliedVolatility']), axis=1)
        g_puts = df_p_filt.apply(lambda row: black_scholes_gamma(s, row['strike'], row['T'], r, row['impliedVolatility']), axis=1)
        total_gex = (g_calls * df_c_filt['openInterest']).sum() - (g_puts * df_p_filt['openInterest']).sum()
        total_gammas.append(total_gex)
    
    total_gammas = np.array(total_gammas)
    zero_cross_idx = np.where(np.diff(np.sign(total_gammas)))[0]
    zgl = None
    if len(zero_cross_idx) > 0:
        idx = zero_cross_idx[0]
        zgl = strikes[idx] - total_gammas[idx] * (strikes[idx+1] - strikes[idx]) / (total_gammas[idx+1] - total_gammas[idx])
        
    return zgl, put_wall, call_wall

def save_to_csv(ticker, spot, zgl, put_wall, call_wall):
    """
    將結果儲存或追加到 CSV 檔案中
    """
    filename = f"{ticker}_gex_history.csv"
    date_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    new_data = pd.DataFrame([{
        'Date': date_str,
        'Spot': round(spot, 2),
        'ZGL': round(zgl, 2) if zgl else None,
        'PutWall': round(put_wall, 2),
        'CallWall': round(call_wall, 2)
    }])
    
    if os.path.exists(filename):
        df_history = pd.read_csv(filename)
        df_history = pd.concat([df_history, new_data], ignore_index=True)
    else:
        df_history = new_data
        
    df_history.to_csv(filename, index=False)
    print(f"Data saved to {filename}")

def main(ticker_symbol):
    print(f"Fetching data for {ticker_symbol}...")
    try:
        spot_price, df_calls, df_puts = get_option_chain_data(ticker_symbol)
        print(f"Current Spot Price: {spot_price:.2f}")
        
        zgl, put_wall, call_wall = calculate_gex_and_levels(spot_price, df_calls, df_puts)
        
        print("-" * 30)
        print(f"Zero Gamma Level (ZGL): {zgl:.2f}" if zgl else "ZGL: Not found")
        print(f"Put Wall: {put_wall:.2f}")
        print(f"Call Wall: {call_wall:.2f}")
        print("-" * 30)
        
        save_to_csv(ticker_symbol, spot_price, zgl, put_wall, call_wall)
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "SPY"
    main(ticker)
