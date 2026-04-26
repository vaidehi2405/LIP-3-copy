import React, { useState, useEffect } from 'react';
import { 
  BarChart3, 
  MessageSquare, 
  Search,
  ChevronDown,
  AlertTriangle,
  TrendingUp,
  Apple,
  Play,
  Calendar,
  Layers,
  ArrowUpRight,
  Info,
  Loader2
} from 'lucide-react';
import './index.css';

function App() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fetch('http://localhost:8000/api/latest');
        if (!response.ok) throw new Error('Network response was not ok');
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
    // Refresh every 5 minutes if data updates scheduled
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
        <p style={{ color: '#6B7280' }}>Failed to connect to the intelligence backend. Please ensure the API is running.</p>
        <button onClick={() => window.location.reload()} style={{ padding: '8px 16px', background: '#00D09C', color: 'white', border: 'none', borderRadius: '8px', fontWeight: 600, cursor: 'pointer' }}>
          Retry Connection
        </button>
      </div>
    );
  }

  return (
    <div className="app-container">
      {/* Groww Style Header */}
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

      {/* Action Required Banner */}
      <div className="alert-banner animate-up">
        <div className="alert-content">
          <AlertTriangle size={18} />
          <span>Action Required: Login Issues increased 42% this week in Google Play Store.</span>
        </div>
        <button className="alert-btn">View Tickets</button>
      </div>

      <main className="main-wrapper">
        <div className="page-header">
          <h1>Product Intelligence Dashboard</h1>
          <p>Real-time analysis of user feedback across iOS and Android platforms ({data.weekKey})</p>
        </div>

        {/* Metrics Grid */}
        <section className="metrics-grid">
          {data.metrics.map((metric, i) => (
            <div key={i} className="metric-card animate-up" style={{ animationDelay: `${0.1 * (i+1)}s` }}>
              <div className="metric-top">
                <span className="metric-label">{metric.label}</span>
                <Info size={16} className="metric-icon" />
              </div>
              <div className="metric-body">
                <div className="metric-value-wrap">
                  <span className="metric-value">{metric.value}</span>
                  <span className={`trend-percent trend-${metric.trendType === 'up' ? 'green' : metric.trendType === 'down' ? 'red' : 'green'}`}>
                    {metric.trend}
                  </span>
                </div>
                <div className="metric-footer">
                  <span className={metric.label === "Reviews Analyzed" ? "footer-blue" : "footer-muted"}>
                    {metric.label === "Avg Rating" ? "4.2 out of 5.0" : metric.label === "Positive Sentiment" ? `${metric.value} vs last week` : metric.label === "Reviews Analyzed" ? "Fresh Data" : "3 New since check"}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </section>

        <div className="content-grid">
          {/* Main Themes Section */}
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
                    <span className="ai-conf">AI conf {theme.confidence || '92%'}</span>
                  </div>
                </div>
                
                <div className="theme-details">
                  <div className="stats-row">
                    <div className="stat-group">
                      <span className="stat-label">Mentions</span>
                      <span className="stat-value">{theme.mentions} <span className="trend-green" style={{fontSize: '10px'}}>+12% WoW</span></span>
                    </div>
                    <div className="stat-group">
                      <span className="stat-label">Platform</span>
                      <div className="stat-value">
                        {theme.platforms.apple > 0 && <Apple size={14} />}
                        {theme.platforms.google > 0 && <Play size={14} />}
                      </div>
                    </div>
                  </div>
                  <div className="stat-group" style={{alignItems: 'flex-end'}}>
                    <span className="stat-label">Last Mention</span>
                    <span className="stat-value" style={{fontSize: '12px', color: 'var(--text-muted)'}}>2h ago</span>
                  </div>
                </div>

                <div className="quote-bubble">
                  <p className="quote-content">"{theme.quote}"</p>
                </div>
              </div>
            ))}
          </section>

          {/* Suggested Actions Sidebar */}
          <aside className="actions-column">
            <span className="section-label">Suggested Actions ({data.actions.length} New)</span>

            {data.actions.map((action, i) => (
              <div key={action.id} className="action-card animate-up" style={{ animationDelay: `${0.8 + i * 0.1}s` }}>
                <div className="action-top">
                  <div className="tag-row">
                    <span className={`action-tag ${action.priority === 'high' ? 'tag-red' : 'tag-blue'}`}>
                      {action.priority === 'high' ? 'High-value' : 'Medium-value'}
                    </span>
                    <span className="action-tag tag-blue">PM MODULE</span>
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
