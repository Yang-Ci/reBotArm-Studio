(function () {
  class ReBotRosClient extends EventTarget {
    constructor(options) {
      super();
      this.url = options && options.url ? options.url : 'ws://127.0.0.1:8765';
      this.namespace = options && options.namespace ? options.namespace : 'rebotarm';
      this.socket = null;
      this.connected = false;
      this.autoReconnect = true;
      this.reconnectDelay = 1400;
      this._manualClose = false;
      this._connectSeq = 0;
      this._nextId = 1;
      this._pending = new Map();
      this._subscriptions = new Map();
      this._lastMessageAt = new Map();
      this._lastTopicDelivery = new Map();
      this._heartbeat = 0;
      this._hello = null;
    }

    connect(url) {
      if (url) this.url = url;
      if (!this.url) this.url = 'ws://127.0.0.1:8765';
      this._manualClose = false;
      if (this.socket && this.socket.readyState === WebSocket.OPEN) return;
      if (this.socket && this.socket.readyState === WebSocket.CONNECTING) return;
      const seq = ++this._connectSeq;
      this._emitStatus('connecting', `正在连接 rebotd ${this.url}`);
      const socket = new WebSocket(this.url);
      this.socket = socket;
      socket.addEventListener('open', async () => {
        if (seq !== this._connectSeq || socket !== this.socket) return;
        this.connected = true;
        try {
          this._hello = await this._rpc('system.hello', {}, 5000);
          this._emitHardwareState(this._hello);
          this._emitStatus('open', `${this._hello.productId || 'RS'} 已连接`);
          this._startHeartbeat();
        } catch (error) {
          this._emitStatus('error', error.message || 'rebotd 握手失败');
          socket.close();
        }
      });
      socket.addEventListener('message', (event) => {
        if (seq === this._connectSeq && socket === this.socket) this._handleMessage(event);
      });
      socket.addEventListener('error', () => {
        if (seq === this._connectSeq && socket === this.socket) {
          this._emitStatus('error', 'rebotd WebSocket 出错');
        }
      });
      socket.addEventListener('close', () => {
        if (seq !== this._connectSeq || socket !== this.socket) return;
        this.connected = false;
        this._stopHeartbeat();
        this._rejectPending('rebotd 连接已断开');
        this._emitStatus('closed', 'rebotd 已断开');
        if (!this._manualClose && this.autoReconnect) {
          window.setTimeout(() => this.connect(), this.reconnectDelay);
        }
      });
    }

    disconnect() {
      this._manualClose = true;
      this.autoReconnect = false;
      this.connected = false;
      this._stopHeartbeat();
      this._rejectPending('rebotd 连接已断开');
      const socket = this.socket;
      this.socket = null;
      ++this._connectSeq;
      if (socket && socket.readyState < WebSocket.CLOSING) socket.close();
      this._emitStatus('closed', 'rebotd 已断开');
    }

    subscribe(topic, type, callback, options) {
      this._subscriptions.set(topic, {
        topic,
        type,
        callback,
        throttleRate: Number(options && options.throttleRate) || 0
      });
    }

    unsubscribe(topic) {
      this._subscriptions.delete(topic);
    }

    enable() {
      return this._trigger('arm.enable');
    }

    scanHardware() {
      return this._rpc('hardware.scan', {}, 5000);
    }

    connectHardware(channel, productId) {
      return this._rpc('hardware.connect', {
        channel,
        productId: productId || 'b601-rs',
        confirm: 'I_UNDERSTAND_REBOTARM_WILL_MOVE'
      }, 30000).then(async (result) => {
        this._hello = await this._rpc('system.hello', {}, 5000);
        this._emitHardwareState(this._hello);
        return result;
      });
    }

    disconnectHardware() {
      return this._rpc('hardware.disconnect', {}, 45000).then(async (result) => {
        this._hello = await this._rpc('system.hello', {}, 5000);
        this._emitHardwareState(this._hello);
        return result;
      });
    }

    disable() {
      return this._trigger('arm.disable', {}, 45000);
    }

    safeHome() {
      return this._trigger('arm.safe_home', {}, 45000);
    }

    startGravityCompensation() {
      return this._rpc('gravity.start').then((result) => ({
        success: true,
        message: result.alreadyActive ? 'gravity compensation already active' : 'gravity compensation started'
      }));
    }

    stopGravityCompensation() {
      return this._trigger('gravity.stop');
    }

    gravityCompensationStatus() {
      return this._rpc('gravity.status').then((result) => ({
        success: Boolean(result.active),
        message: result.active
          ? 'gravity compensation active'
          : (result.fault ? `gravity compensation inactive; last fault: ${result.fault}` : 'gravity compensation inactive')
      }));
    }

    setGripper(position, maxEffort) {
      void maxEffort;
      return this._rpc('gripper.set', { positionRad: Number(position), wait: true }, 10000)
        .then((result) => ({
          success: Boolean(result.reached),
          reached_position: result.positionRad,
          message: result.reached ? 'gripper target reached' : 'gripper target timeout'
        }));
    }

    releaseGripper() {
      return this._trigger('gripper.release');
    }

    holdGripper() {
      return this._trigger('gripper.hold');
    }

    startGripperAssist() {
      return this._trigger('gripper.assist_start');
    }

    gripperAssistStatus() {
      return this._rpc('gripper.status').then((result) => ({
        success: Boolean(result.assistActive),
        message: result.manualFree ? 'gripper released for manual movement' : 'gripper holding current position'
      }));
    }

    moveToPose(pose, duration) {
      return this._rpc('tcp.move_trajectory', {
        ...poseToXyzRpy(pose),
        duration: Number(duration) || 2
      }, Math.max(30000, ((Number(duration) || 2) + 10) * 1000)).then((result) => ({
        ...result,
        accepted: Boolean(result.success),
        message: result.success ? 'move trajectory complete' : 'move trajectory failed'
      }));
    }

    solveMoveToPoseIK(pose) {
      return this._rpc('tcp.move_ik', poseToXyzRpy(pose), 20000).then((result) => ({
        success: Boolean(result.success),
        message: result.success ? 'IK target accepted' : 'IK failed',
        q_solution: result.jointSolution || []
      }));
    }

    followJointTrajectory(jointNames, points, options) {
      const expected = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'joint6'];
      if (JSON.stringify(jointNames) !== JSON.stringify(expected)) {
        return Promise.reject(new Error(`trajectory joint names must be ${expected.join(', ')}`));
      }
      const converted = (points || []).map((point) => ({
        positions: (point.positions || []).map(Number),
        time: rosTimeToSeconds(point.time_from_start)
      }));
      const timeoutMs = Math.max(30000, (this._estimateTrajectoryDuration(points) + 10) * 1000);
      return this._rpc('trajectory.execute', {
        points: converted,
        teaching: Boolean(options && options.profile === 'teaching-replay')
      }, timeoutMs).then((result) => ({
        ...result,
        accepted: true,
        completed: true,
        message: 'joint trajectory complete'
      }));
    }

    getRosTopics() {
      const ns = `/${this.namespace}`;
      return Promise.resolve({ topics: [
        `${ns}/joint_states`,
        `${ns}/mujoco/joint_states`,
        `${ns}/arm_status`,
        `${ns}/gripper/state`
      ] });
    }

    getRosServices() {
      const ns = `/${this.namespace}`;
      return Promise.resolve({ services: [
        `${ns}/enable`, `${ns}/disable`, `${ns}/safe_home`,
        `${ns}/gravity_compensation/start`, `${ns}/gravity_compensation/stop`,
        `${ns}/gravity_compensation/status`, `${ns}/gripper/release`,
        `${ns}/gripper/hold`, `${ns}/gripper/assist/start`,
        `${ns}/gripper/assist/status`,
        `${ns}/follow_joint_trajectory/_action/send_goal`,
        `${ns}/move_to_pose/_action/send_goal`
      ] });
    }

    getLastMessageAt(topic) {
      return this._lastMessageAt.get(topic) || 0;
    }

    publishJointCommand(jointName, position, options) {
      this._notify('joint.set_target', {
        name: jointName,
        position: Number(position),
        velocityLimit: options && Number.isFinite(options.vlim) ? options.vlim : 1.2
      });
    }

    publishGripperCommand(position, vlim) {
      void vlim;
      this._notify('gripper.set', { positionRad: Number(position), wait: false });
    }

    publishTargetPose(pose) {
      this._lastTargetPose = pose;
    }

    advertise() {}

    publish(topic, msg) {
      const jointMatch = topic.match(/\/joints\/([^/]+)\/cmd\/mit$/);
      if (jointMatch) {
        this.publishJointCommand(jointMatch[1], msg.pos, { vlim: msg.vel });
      } else if (/\/gripper\/cmd\/mit$/.test(topic)) {
        this.publishGripperCommand(msg.pos, msg.vel);
      }
    }

    callService(service, type, args, options) {
      void type;
      const timeout = Number(options && options.timeoutMs) || 10000;
      const mappings = [
        [/\/enable$/, 'arm.enable'],
        [/\/disable$/, 'arm.disable'],
        [/\/safe_home$/, 'arm.safe_home'],
        [/\/gravity_compensation\/start$/, 'gravity.start'],
        [/\/gravity_compensation\/stop$/, 'gravity.stop'],
        [/\/gravity_compensation\/status$/, 'gravity.status'],
        [/\/gripper\/release$/, 'gripper.release'],
        [/\/gripper\/hold$/, 'gripper.hold'],
        [/\/gripper\/assist\/start$/, 'gripper.assist_start'],
        [/\/gripper\/assist\/status$/, 'gripper.status']
      ];
      const entry = mappings.find(([pattern]) => pattern.test(service));
      if (!entry) return Promise.reject(new Error(`unsupported legacy service: ${service}`));
      return this._rpc(entry[1], args || {}, timeout);
    }

    sendActionGoal(actionName, actionType, goal, options) {
      void actionType;
      if (/follow_joint_trajectory$/.test(actionName)) {
        return this.followJointTrajectory(
          goal.trajectory.joint_names,
          goal.trajectory.points,
          { profile: goal.trajectory.header && goal.trajectory.header.frame_id === 'rebotarm_teaching_replay' ? 'teaching-replay' : '' }
        );
      }
      if (/move_to_pose$/.test(actionName)) {
        return this.moveToPose(goal.target_pose, goal.duration);
      }
      return Promise.reject(new Error(`unsupported legacy action: ${actionName}`));
    }

    _trigger(method, params, timeout) {
      return this._rpc(method, params || {}, timeout || 10000).then((result) => ({
        success: true,
        message: result && result.message ? result.message : method
      }));
    }

    _rpc(method, params, timeoutMs) {
      const id = `request:${this._nextId++}`;
      return new Promise((resolve, reject) => {
        if (!this.connected || !this.socket || this.socket.readyState !== WebSocket.OPEN) {
          reject(new Error('rebotd 未连接'));
          return;
        }
        const timer = window.setTimeout(() => {
          if (!this._pending.has(id)) return;
          this._pending.delete(id);
          reject(new Error(`请求超时：${method}`));
        }, Number(timeoutMs) || 10000);
        this._pending.set(id, {
          resolve: (value) => { window.clearTimeout(timer); resolve(value); },
          reject: (error) => { window.clearTimeout(timer); reject(error); }
        });
        this.socket.send(JSON.stringify({ id, method, params: params || {} }));
      });
    }

    _notify(method, params) {
      if (!this.connected || !this.socket || this.socket.readyState !== WebSocket.OPEN) return;
      this.socket.send(JSON.stringify({ method, params: params || {} }));
    }

    _handleMessage(event) {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch (_) {
        this._emitStatus('error', '收到无法解析的 rebotd 消息');
        return;
      }
      if (message.event === 'telemetry') {
        this._dispatchTelemetry(message.data || {});
        return;
      }
      if (message.event === 'error') {
        this.dispatchEvent(new CustomEvent('daemon-error', { detail: message.data || {} }));
        return;
      }
      const pending = this._pending.get(message.id);
      if (!pending) return;
      this._pending.delete(message.id);
      if (message.ok) pending.resolve(message.result || {});
      else pending.reject(new Error(message.error && message.error.message ? message.error.message : 'rebotd request failed'));
    }

    _dispatchTelemetry(data) {
      const stamp = toRosStamp(data.timestamp);
      const names = Array.isArray(data.jointNames) ? data.jointNames : [];
      const jointMessage = {
        header: { stamp, frame_id: 'base_link' },
        name: names,
        position: data.position || [],
        velocity: data.velocity || [],
        effort: data.torque || []
      };
      const ns = `/${this.namespace}`;
      this._emitHardwareState(data);
      this._emitTopic(`${ns}/joint_states`, jointMessage);
      this._emitTopic(`${ns}/mujoco/joint_states`, jointMessage);
      const gripper = data.gripper || {};
      this._emitTopic(`${ns}/gripper/state`, {
        header: { stamp, frame_id: 'gripper' },
        joint_name: 'gripper',
        position: Number(gripper.positionRad) || 0,
        velocity: Number(gripper.velocity) || 0,
        torque: Number(gripper.torque) || 0,
        status_code: Number(gripper.statusCode) || 0
      });
      this._emitTopic(`${ns}/arm_status`, {
        header: { stamp, frame_id: 'base_link' },
        mode: data.mode || 'mit',
        enabled: Boolean(data.enabled),
        control_loop_active: Boolean(data.controlLoopActive),
        state_machine: data.stateMachine || 'IDLE',
        joint_names: names,
        per_joint_status_code: data.statusCodes || [],
        error_codes: data.errors || []
      });
    }

    _emitTopic(topic, message) {
      const subscription = this._subscriptions.get(topic);
      if (!subscription) return;
      const now = Date.now();
      const last = this._lastTopicDelivery.get(topic) || 0;
      if (subscription.throttleRate && now - last < subscription.throttleRate) return;
      this._lastTopicDelivery.set(topic, now);
      this._lastMessageAt.set(topic, now);
      subscription.callback(message, topic);
    }

    _emitHardwareState(data) {
      this.dispatchEvent(new CustomEvent('hardware-state', { detail: {
        connected: Boolean(data && data.hardwareConnected),
        driver: data && data.driver ? data.driver : 'disconnected',
        channel: data && data.channel ? data.channel : '',
        enabled: Boolean(data && data.enabled),
        stateMachine: data && data.stateMachine ? data.stateMachine : 'DISCONNECTED'
      } }));
    }

    _startHeartbeat() {
      this._stopHeartbeat();
      this._heartbeat = window.setInterval(() => {
        if (this.connected) this._rpc('system.ping', {}, 2000).catch(() => {});
      }, 1000);
    }

    _stopHeartbeat() {
      if (this._heartbeat) window.clearInterval(this._heartbeat);
      this._heartbeat = 0;
    }

    _estimateTrajectoryDuration(points) {
      const list = Array.isArray(points) ? points : [];
      return list.reduce((maximum, point) => Math.max(maximum, rosTimeToSeconds(point.time_from_start)), 0);
    }

    _rejectPending(message) {
      this._pending.forEach((pending) => pending.reject(new Error(message)));
      this._pending.clear();
    }

    _emitStatus(state, message) {
      this.dispatchEvent(new CustomEvent('status', { detail: { state, message } }));
    }
  }

  function rosTimeToSeconds(stamp) {
    return (Number(stamp && stamp.sec) || 0) + (Number(stamp && stamp.nanosec) || 0) * 1e-9;
  }

  function toRosStamp(seconds) {
    const value = Number(seconds) || Date.now() / 1000;
    const sec = Math.floor(value);
    return { sec, nanosec: Math.floor((value - sec) * 1e9) };
  }

  function poseToXyzRpy(pose) {
    const position = pose && pose.position ? pose.position : pose || {};
    const quaternion = pose && pose.orientation ? pose.orientation : { x: 0, y: 0, z: 0, w: 1 };
    const x = Number(quaternion.x) || 0;
    const y = Number(quaternion.y) || 0;
    const z = Number(quaternion.z) || 0;
    const w = Number.isFinite(Number(quaternion.w)) ? Number(quaternion.w) : 1;
    const sinr = 2 * (w * x + y * z);
    const cosr = 1 - 2 * (x * x + y * y);
    const roll = Math.atan2(sinr, cosr);
    const sinp = 2 * (w * y - z * x);
    const pitch = Math.abs(sinp) >= 1 ? Math.sign(sinp) * Math.PI / 2 : Math.asin(sinp);
    const siny = 2 * (w * z + x * y);
    const cosy = 1 - 2 * (y * y + z * z);
    const yaw = Math.atan2(siny, cosy);
    return {
      x: Number(position.x) || 0,
      y: Number(position.y) || 0,
      z: Number(position.z) || 0,
      roll,
      pitch,
      yaw
    };
  }

  window.ReBotRosClient = ReBotRosClient;
})();
