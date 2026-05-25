import streamlit as st


def cached_dart(func):
    """DART API 응답 1시간 캐싱"""
    return st.cache_data(ttl=3600)(func)


def cached_search(func):
    """뉴스/검색 결과 10분 캐싱"""
    return st.cache_data(ttl=600)(func)
