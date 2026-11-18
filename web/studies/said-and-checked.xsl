<?xml version="1.0" encoding="UTF-8"?>
<!-- Shows a Said & Checked RSS feed as a readable page when it is opened in a browser.
     Feed readers ignore this stylesheet and read the RSS. -->
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
                xmlns:atom="http://www.w3.org/2005/Atom">
  <xsl:output method="html" encoding="UTF-8" indent="no"/>

  <!-- Percent-encodes the characters that appear in this site's feed URLs. -->
  <xsl:template name="encode">
    <xsl:param name="s"/>
    <xsl:if test="string-length($s) &gt; 0">
      <xsl:variable name="c" select="substring($s, 1, 1)"/>
      <xsl:choose>
        <xsl:when test="$c = ':'">%3A</xsl:when>
        <xsl:when test="$c = '/'">%2F</xsl:when>
        <xsl:otherwise><xsl:value-of select="$c"/></xsl:otherwise>
      </xsl:choose>
      <xsl:call-template name="encode">
        <xsl:with-param name="s" select="substring($s, 2)"/>
      </xsl:call-template>
    </xsl:if>
  </xsl:template>

  <xsl:template match="/rss/channel">
    <xsl:variable name="feed" select="atom:link[@rel='self']/@href"/>
    <xsl:variable name="enc">
      <xsl:call-template name="encode"><xsl:with-param name="s" select="$feed"/></xsl:call-template>
    </xsl:variable>
    <html lang="en">
      <head>
        <meta charset="UTF-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1"/>
        <title><xsl:value-of select="title"/></title>
        <style>
          :root { --bg:#ffffff; --fg:#1a1a1a; --muted:#5f6368; --line:#e3e3e3; --box:#f5f7fa;
                  --accent:#1a56db; --btn-fg:#ffffff; }
          @media (prefers-color-scheme: dark) {
            :root { --bg:#141414; --fg:#ececec; --muted:#a0a0a0; --line:#2e2e2e; --box:#1e2228;
                    --accent:#6b9cff; --btn-fg:#0d0d0d; }
          }
          body { margin:0; background:var(--bg); color:var(--fg);
                 font:16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
          main { max-width:760px; margin:0 auto; padding:32px 16px 64px; }
          h1 { font-size:1.6rem; margin:0 0 4px; }
          .about { color:var(--muted); margin:0 0 24px; }
          .sub { background:var(--box); border:1px solid var(--line); border-radius:10px;
                 padding:18px 20px; margin-bottom:32px; }
          .sub p { margin:0 0 12px; }
          .btns a { display:inline-block; background:var(--accent); color:var(--btn-fg);
                    text-decoration:none; font-weight:600; padding:8px 16px; border-radius:6px;
                    margin:0 8px 8px 0; }
          .url { display:block; font:13px/1.4 ui-monospace, Menlo, monospace; word-break:break-all;
                 background:var(--bg); border:1px solid var(--line); border-radius:6px;
                 padding:8px 10px; margin-top:4px; user-select:all; }
          .hint { color:var(--muted); font-size:.9rem; }
          article { border-top:1px solid var(--line); padding:20px 0; }
          article h2 { font-size:1.15rem; margin:0 0 2px; }
          article h2 a { color:var(--fg); }
          .date { color:var(--muted); font-size:.9rem; margin-bottom:8px; }
          a { color:var(--accent); }
          li { margin-bottom:10px; }
        </style>
      </head>
      <body>
        <main>
          <h1><xsl:value-of select="title"/></h1>
          <p class="about"><xsl:value-of select="description"/></p>
          <div class="sub">
            <p><strong>Get this in a feed reader.</strong> Each day's Said &amp; Checked arrives
              there as it is published, with the false and contradicted statements first.</p>
            <div class="btns">
              <a href="https://feedly.com/i/subscription/feed%2F{$enc}" target="_blank" rel="noopener">Add to Feedly</a>
              <a href="https://www.inoreader.com/?add_feed={$enc}" target="_blank" rel="noopener">Add to Inoreader</a>
            </div>
            <p class="hint">Other readers (NetNewsWire, Reeder, Outlook, Thunderbird): add this
              address.<span class="url"><xsl:value-of select="$feed"/></span></p>
          </div>
          <xsl:if test="not(item)">
            <p class="hint">No days in this feed yet. New days appear here when a matching
              statement is published.</p>
          </xsl:if>
          <xsl:for-each select="item">
            <article>
              <h2><a href="{link}"><xsl:value-of select="title"/></a></h2>
              <div class="date"><xsl:value-of select="substring(pubDate, 1, 16)"/></div>
              <div><xsl:value-of select="description" disable-output-escaping="yes"/></div>
            </article>
          </xsl:for-each>
          <p class="hint"><a href="{link}">All days of Said &amp; Checked</a></p>
        </main>
      </body>
    </html>
  </xsl:template>
</xsl:stylesheet>
