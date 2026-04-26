import React, { useState, useEffect } from 'react';
import {
  Search,
  ChevronDown,
  AlertTriangle,
  Apple,
  Play,
  ArrowUpRight,
  Info,
  Loader2,
} from 'lucide-react';
import './index.css';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

function trendClass(trendType) {
  if (trendType === 'up') return 'green';
  if (trendType === 'down') return 'red';
  return 'green';
}

function App() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setError(null);
        const response = await fetch(`${API_BASE}/api/latest`);
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(body.detail || 'Network response was not ok');
        }
        const jsonData = await response.json();
        setData(jsonData);
      } catch (err) {
        console.error('Error fetching data:', err);
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 300000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div style={{ height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#F9FAFB' }}>
        <Loader2 className="animate-spin" size={48} color="#00D09C" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div style={{ height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#F9FAFB', flexDirection: 'column', gap: '16px' }}>
        <AlertTriangle size={48} color="#EF4444" />
        <h2 style={{ fontWeight: 700 }}>Something went wrong</h2>
        <p style={{ color: '#6B7280', textAlign: 'center', maxWidth: 500 }}>{error || 'Failed to connect to backend.'}</p>
        <button onClick={() => window.location.reload()} style={{ padding: '8px 16px', background: '#00D09C', color: 'white', border: 'none', borderRadius: '8px', fontWeight: 600, cursor: 'pointer' }}>
          Retry Connection
        </button>
      </div>
    );
  }

  return (
    <div className="app-container">
      <header className="top-header">
        <div className="logo-section">
          <div className="brand-wrapper">
            <div className="groww-logo">G</div>
            <div className="internal-text">
              Internal Tool | Review Pulse
              <span className="divider">|</span>
              <span className="ai-pill">AI GENERATED INSIGHTS</span>
            </div>
          </div>
        </div>

        <div className="search-section">
          <Search className="search-icon" size={16} />
          <input type="text" className="search-bar" placeholder="Search insights, themes, or reviews..." />
        </div>

        <div className="header-utils">
          <div className="date-text">
            {data.dateRange}
            <ChevronDown size={14} />
          </div>
          <div className="profile-avatar">SD</div>
        </div>
      </header>

      {data.alert && (
        <div className="alert-banner animate-up">
          <div className="alert-content">
            <AlertTriangle size={18} />
            <span>{data.alert.message}</span>
          </div>
          <button className="alert-btn">{data.alert.cta || 'View Details'}</button>
        </div>
      )}

      <main className="main-wrapper">
        <div className="page-header">
          <h1>Product Intelligence Dashboard</h1>
          <p>Live analysis of weekly feedback across iOS and Android ({data.weekKey})</p>
        </div>

        <section className="metrics-grid">
          {data.metrics.map((metric, i) => (
            <div key={i} className="metric-card animate-up" style={{ animationDelay: `${0.1 * (i + 1)}s` }}>
              <div className="metric-top">
                <span className="metric-label">{metric.label}</span>
                <Info size={16} className="metric-icon" />
              </div>
              <div className="metric-body">
                <div className="metric-value-wrap">
                  <span className="metric-value">{metric.value}</span>
                  <span className={`trend-percent trend-${trendClass(metric.trendType)}`}>
                    {metric.trend}
                  </span>
                </div>
                <div className="metric-footer">
                  <span className="footer-muted">{metric.context || ''}</span>
                </div>
              </div>
            </div>
          ))}
        </section>

        <div className="content-grid">
          <section className="themes-column">
            <span className="section-label">Top Performance Themes ({data.themes.length} Total)</span>

            {data.themes.map((theme, i) => (
              <div key={theme.id} className="theme-card animate-up" style={{ animationDelay: `${0.5 + i * 0.1}s` }}>
                <div className="theme-card-header">
                  <div className="theme-title-box">
                    <span className="theme-rank">#{theme.id}</span>
                    <span className="theme-name">{theme.name}</span>
                  </div>
                  <div className="theme-meta">
                    <span className={`sentiment-pill ${theme.sentiment}`}>{theme.sentiment}</span>
                    <span className="ai-conf">AI conf {theme.confidence || 'N/A'}</span>
                  </div>
                </div>

                <div className="theme-details">
                  <div className="stats-row">
                    <div className="stat-group">
                      <span className="stat-label">Mentions</span>
                      <span className="stat-value">{theme.mentions} <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>({theme.mention_share})</span></span>
                    </div>
                    <div className="stat-group">
                      <span className="stat-label">Platform</span>
                      <div className="stat-value">
                        {theme.platforms?.includes('apple') && <Apple size={14} />}
                        {theme.platforms?.includes('google') && <Play size={14} />}
                      </div>
                    </div>
                  </div>
                  <div className="stat-group" style={{ alignItems: 'flex-end' }}>
                    <span className="stat-label">Sources</span>
                    <span className="stat-value" style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                      {theme.platform_counts?.apple || 0} iOS / {theme.platform_counts?.google || 0} Android
                    </span>
                  </div>
                </div>

                <div className="quote-bubble">
                  <p className="quote-content">"{theme.quote}"</p>
                </div>
              </div>
            ))}
          </section>

          <aside className="actions-column">
            <span className="section-label">Suggested Actions ({data.actions.length})</span>

            {data.actions.map((action, i) => (
              <div key={action.id} className="action-card animate-up" style={{ animationDelay: `${0.8 + i * 0.1}s` }}>
                <div className="action-top">
                  <div className="tag-row">
                    <span className={`action-tag ${action.priority === 'high' ? 'tag-red' : 'tag-blue'}`}>
                      {action.priority === 'high' ? 'High-priority' : 'Medium-priority'}
                    </span>
                    <span className="action-tag tag-blue">{action.category || 'PM MODULE'}</span>
                  </div>
                  <ArrowUpRight size={18} color="var(--text-muted)" cursor="pointer" />
                </div>
                <div className="action-title">{action.title}</div>
                <div className="action-desc">{action.description}</div>
                <div className="btn-group">
                  <button className="btn-jira">Create Jira Ticket</button>
                  <button className="btn-done">Mark Done</button>
                </div>
              </div>
            ))}
          </aside>
        </div>
      </main>
    </div>
  );
}

export default App;
