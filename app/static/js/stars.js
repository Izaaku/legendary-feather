// Canvas Star Background Animation

class StarField {
  constructor(canvasId = 'stars-canvas') {
    this.canvas = document.getElementById(canvasId);
    if (!this.canvas) {
      // Create canvas if it doesn't exist
      this.canvas = document.createElement('canvas');
      this.canvas.id = canvasId;
      this.canvas.style.position = 'fixed';
      this.canvas.style.top = '0';
      this.canvas.style.left = '0';
      this.canvas.style.zIndex = '-1';
      document.body.insertBefore(this.canvas, document.body.firstChild);
    }

    this.ctx = this.canvas.getContext('2d');
    this.stars = [];
    this.mouseX = window.innerWidth / 2;
    this.mouseY = window.innerHeight / 2;

    this.resizeCanvas();
    this.generateStars();
    this.setupEventListeners();
    this.animate();
  }

  resizeCanvas() {
    this.canvas.width = window.innerWidth;
    this.canvas.height = window.innerHeight;
  }

  generateStars() {
    this.stars = [];
    const starCount = Math.floor((this.canvas.width * this.canvas.height) / 15000);

    for (let i = 0; i < starCount; i++) {
      this.stars.push({
        x: Math.random() * this.canvas.width,
        y: Math.random() * this.canvas.height,
        radius: Math.random() * 1.5,
        opacity: Math.random() * 0.5 + 0.5,
        twinkleSpeed: Math.random() * 0.03 + 0.01,
        twinklePhase: Math.random() * Math.PI * 2,
        vx: (Math.random() - 0.5) * 0.3,
        vy: (Math.random() - 0.5) * 0.3,
      });
    }
  }

  setupEventListeners() {
    window.addEventListener('resize', () => this.resizeCanvas());

    document.addEventListener('mousemove', (e) => {
      this.mouseX = e.clientX;
      this.mouseY = e.clientY;
    });

    document.addEventListener('mouseleave', () => {
      this.mouseX = this.canvas.width / 2;
      this.mouseY = this.canvas.height / 2;
    });
  }

  drawStar(star) {
    // Calculate twinkle effect
    const twinkle = Math.sin(star.twinklePhase) * 0.5 + 0.5;
    const opacity = star.opacity * twinkle;

    // Calculate distance from mouse for glow effect
    const dx = star.x - this.mouseX;
    const dy = star.y - this.mouseY;
    const distance = Math.sqrt(dx * dx + dy * dy);
    const glowRange = 200;
    const glowIntensity = Math.max(0, 1 - distance / glowRange) * 0.5;

    // Draw star with glow
    this.ctx.fillStyle = `rgba(212, 175, 55, ${opacity + glowIntensity})`;
    this.ctx.shadowColor = `rgba(212, 175, 55, ${glowIntensity})`;
    this.ctx.shadowBlur = 10 * glowIntensity;

    this.ctx.beginPath();
    this.ctx.arc(star.x, star.y, star.radius, 0, Math.PI * 2);
    this.ctx.fill();

    this.ctx.shadowBlur = 0;
  }

  updateStar(star) {
    // Update position
    star.x += star.vx;
    star.y += star.vy;

    // Wrap around edges
    if (star.x < 0) star.x = this.canvas.width;
    if (star.x > this.canvas.width) star.x = 0;
    if (star.y < 0) star.y = this.canvas.height;
    if (star.y > this.canvas.height) star.y = 0;

    // Update twinkle
    star.twinklePhase += star.twinkleSpeed;
  }

  drawConstellations() {
    // Draw subtle constellation lines between nearby stars
    const connectionDistance = 150;

    for (let i = 0; i < this.stars.length; i++) {
      for (let j = i + 1; j < Math.min(i + 5, this.stars.length); j++) {
        const dx = this.stars[i].x - this.stars[j].x;
        const dy = this.stars[i].y - this.stars[j].y;
        const distance = Math.sqrt(dx * dx + dy * dy);

        if (distance < connectionDistance) {
          const opacity = (1 - distance / connectionDistance) * 0.1;
          this.ctx.strokeStyle = `rgba(212, 175, 55, ${opacity})`;
          this.ctx.lineWidth = 0.5;
          this.ctx.beginPath();
          this.ctx.moveTo(this.stars[i].x, this.stars[i].y);
          this.ctx.lineTo(this.stars[j].x, this.stars[j].y);
          this.ctx.stroke();
        }
      }
    }
  }

  animate() {
    // Clear canvas with fade effect
    this.ctx.fillStyle = 'rgba(10, 14, 39, 0.1)';
    this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);

    // Update and draw stars
    for (let star of this.stars) {
      this.updateStar(star);
      this.drawStar(star);
    }

    // Draw constellation lines
    this.drawConstellations();

    // Continue animation
    requestAnimationFrame(() => this.animate());
  }
}

// Initialize star field when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    new StarField();
  });
} else {
  new StarField();
}
