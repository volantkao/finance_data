import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import norm
from datetime import datetime
import matplotlib.pyplot as plt

def black_scholes_gamma(S, K, T, r, sigma):
    """
    計算 Black-Scholes Gamma
    S: 現貨價格
    K: 履約價
    T: 到期時間 (年)
    r: 無風險利率
    sigma: 隱含波動率 (IV)
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
    
    # 獲取現貨價格
    # 使用 fast_info 或 history 獲取最新價格
    history = ticker.history(period="1d")
    if history.empty:
        raise ValueError(f"Could not get price for {ticker_symbol}")
    spot_price = history['Close'].iloc[-1]
    
    all_calls = []
    all_puts = []
    
    today = datetime.now()
    
    for exp in expirations:
        opt = ticker.option_chain(exp)
        
        # 計算到期時間 (T)
        exp_date = datetime.strptime(exp, '%Y-%m-%d')
        T = (exp_date - today).days / 365.0
        if T <= 0: T = 1/365.0 # 避免 0DTE 導致除以零
        
        calls = opt.calls.copy()
        puts = opt.puts.copy()
        
        calls['T'] = T
        puts['T'] = T
        calls['type'] = 'call'
        puts['type'] = 'put'
        
        all_calls.append(calls)
        all_puts.append(puts)
        
    df_calls = pd.concat(all_calls)
    df_puts = pd.concat(all_puts)
    
    return spot_price, df_calls, df_puts

def calculate_gex(spot_price, df_calls, df_puts, r=0.04):
    """
    計算 Gamma Exposure (GEX)
    """
    # 處理缺失值
    df_calls = df_calls.dropna(subset=['impliedVolatility', 'openInterest'])
    df_puts = df_puts.dropna(subset=['impliedVolatility', 'openInterest'])
    
    # 計算每一檔的 Gamma
    df_calls['gamma'] = df_calls.apply(lambda row: black_scholes_gamma(spot_price, row['strike'], row['T'], r, row['impliedVolatility']), axis=1)
    df_puts['gamma'] = df_puts.apply(lambda row: black_scholes_gamma(spot_price, row['strike'], row['T'], r, row['impliedVolatility']), axis=1)
    
    # 計算 GEX (假設 Dealer 是 Long Call / Short Put)
    # GEX = Gamma * OI * ContractSize (100) * SpotPrice * 0.01 (1% move)
    # 單位通常為 $ Billions per 1% move
    df_calls['GEX'] = df_calls['gamma'] * df_calls['openInterest'] * 100 * spot_price * spot_price * 0.01
    df_puts['GEX'] = df_puts['gamma'] * df_puts['openInterest'] * 100 * spot_price * spot_price * 0.01 * -1
    
    return df_calls, df_puts

def find_zgl_and_walls(spot_price, df_calls, df_puts, r=0.04):
    """
    尋找 Zero Gamma Level, Put Wall, Call Wall
    """
    # Put Wall: 最大 Put OI 的履約價
    put_wall = df_puts.groupby('strike')['openInterest'].sum().idxmax()
    
    # Call Wall: 最大 Call OI 的履約價
    call_wall = df_calls.groupby('strike')['openInterest'].sum().idxmax()
    
    # 計算 ZGL (Gamma Flip)
    # 我們模擬現貨價格變動，尋找總 GEX 從正轉負的點
    # 為了加速計算，我們縮小範圍並減少採樣點
    strikes = np.linspace(spot_price * 0.9, spot_price * 1.1, 40)
    total_gammas = []
    
    # 預先過濾掉 OI 為 0 的數據
    df_calls_filtered = df_calls[df_calls['openInterest'] > 0].copy()
    df_puts_filtered = df_puts[df_puts['openInterest'] > 0].copy()

    for s in strikes:
        g_calls = df_calls_filtered.apply(lambda row: black_scholes_gamma(s, row['strike'], row['T'], r, row['impliedVolatility']), axis=1)
        g_puts = df_puts_filtered.apply(lambda row: black_scholes_gamma(s, row['strike'], row['T'], r, row['impliedVolatility']), axis=1)
        
        total_gex = (g_calls * df_calls_filtered['openInterest']).sum() - (g_puts * df_puts_filtered['openInterest']).sum()
        total_gammas.append(total_gex)
    
    total_gammas = np.array(total_gammas)
    
    # 尋找穿過 0 的點
    zero_cross_idx = np.where(np.diff(np.sign(total_gammas)))[0]
    if len(zero_cross_idx) > 0:
        idx = zero_cross_idx[0]
        # 線性插值尋找更精確的 ZGL
        zgl = strikes[idx] - total_gammas[idx] * (strikes[idx+1] - strikes[idx]) / (total_gammas[idx+1] - total_gammas[idx])
    else:
        zgl = None
        
    return zgl, put_wall, call_wall

def main(ticker_symbol):
    print(f"Fetching data for {ticker_symbol}...")
    spot_price, df_calls, df_puts = get_option_chain_data(ticker_symbol)
    print(f"Current Spot Price: {spot_price:.2f}")
    
    df_calls, df_puts = calculate_gex(spot_price, df_calls, df_puts)
    zgl, put_wall, call_wall = find_zgl_and_walls(spot_price, df_calls, df_puts)
    
    print("-" * 30)
    print(f"Zero Gamma Level (ZGL): {zgl:.2f}" if zgl else "ZGL: Not found")
    print(f"Put Wall: {put_wall:.2f}")
    print(f"Call Wall: {call_wall:.2f}")
    print("-" * 30)
    
    # 簡單繪圖 (可選)
    # ... 這裡可以加入繪圖邏輯 ...

if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "SPY"
    main(ticker)
