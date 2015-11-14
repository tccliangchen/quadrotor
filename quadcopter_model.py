import numpy as np
from scipy.integrate import odeint


class Quadcopter(object):

    def __init__(self, save_state=True, config={}):
        """
        Parameters
        ----------
        save_state: Boolean
            Decides whether the state of the system should be saved
            and returned at the end
        """
        self.config = {
            # Constants
            'gravity': 9.806,  # Earth gravity [m s^-2]

            # Vehicle related parameters
            'mass': 0.468,  # Mass [kg]
            'length': 0.17,  # Center to rotor length [m]
            # Intertia [Ixx, Iyy, Izz]
            'inertia': np.array([0.0023, 0.0023, 0.0046]),  # [kg m^2]
            'thrustToDrag': 0.016  # thrust to drag constant [m]
        }

        self.save_state = save_state
        self._dt = 0.001  # seconds
        self.config.update(config)
        self.initialize_state()

    def initialize_state(self):
        self.state = {
            # Position [x, y, z] of the quad in inertial frame
            'position': np.zeros(3),
            # Velocity [dx/dt, dy/dt, dz/dt] of the quad in inertial frame
            'velocity': np.zeros(3),
            # Euler angles [phi, theta, psi]
            'orientation': np.zeros(3),
            # Angular velocity [p, q, r]
            'ang_velocity': np.zeros(3)
        }

    def motor_thrust(self, moments, coll_thrust):
        """Compute the individual motor thrusts

        Parameters
        ----------
        moments : numpy.array
            The moments along each of the axis [Mp, Mq, Mr]
        coll_thrust : float
            The collective thrust generated by all motors
        Returns
        -------
        numpy.array
            The thrust generated by each motor [T1, T2, T3, T4]
        """
        [mp, mq, mr] = moments
        thrust = np.zeros(4)
        temp1add = coll_thrust + mr / self.config['thrustToDrag']
        temp1sub = coll_thrust - mr / self.config['thrustToDrag']

        temp2p = 2 * mp / self.config['length']
        temp2q = 2 * mq / self.config['length']

        thrust[0] = temp1add - temp2q
        thrust[1] = temp1sub + temp2p
        thrust[2] = temp1add + temp2q
        thrust[3] = temp1sub - temp2p

        return thrust / 4.0

    def dt_eulerangles_to_angular_velocity(self, dtEuler, euler_angles):
        """Convert the Euler angle derivatives to angular velocity
        dtEuler = np.array([dphi/dt, dtheta/dt, dpsi/dt])
        """
        return np.dot(self.angular_rotation_matrix(euler_angles), dtEuler)

    def acceleration(self, thrusts, euler_angles):
        """Compute the acceleration in inertial reference frame
        thrust = np.array([Motor1, .... Motor4])
        """
        force_z_body = np.sum(thrusts) / self.config['mass']
        rotation_matrix = self.rotation_matrix(euler_angles)
        # print rotation_matrix
        force_body = np.array([0, 0, force_z_body])
        return np.dot(rotation_matrix, force_body) - np.array([0, 0, self.config['gravity']])

    def angular_acceleration(self, omega, thrust):
        """Compute the angular acceleration in body frame
        omega = angular velocity :- np.array([p, q, r])
        """
        [t1, t2, t3, t4] = thrust
        thrust_matrix = np.array([self.config['length'] * (t2 - t4),
                                  self.config['length'] * (t3 - t1),
                                  self.config['thrustToDrag'] * (t1 - t2 + t3 - t4)])

        inverse_inertia = np.linalg.inv(self.inertia_matrix)
        part1 = np.dot(inverse_inertia, thrust_matrix)
        part2 = np.dot(inverse_inertia, omega)
        part3 = np.dot(self.inertia_matrix, omega)
        cross = np.cross(part2, part3)
        return part1 - cross

    def angular_velocity_to_dt_eulerangles(self, omega, euler_angles):
        """Compute Euler angles from angular velocity
        omega = angular velocity :- np.array([p, q, r])
        """
        rotation_matrix = np.linalg.inv(self.angular_rotation_matrix(euler_angles))
        return np.dot(rotation_matrix, omega)

    def moments(self, desired_acc, angular_vel):
        """Compute the moments

        Parameters
        ----------
        desired_acc : numpy.array
            The desired angular acceleration that the system should achieve. This
            should be of form [dp/dt, dq/dt, dr/dt]
        angular_vel : numpy.array
            The current angular velocity of the system. This
            should be of form [p, q, r]

        Returns
        -------
        numpy.array
            The desired moments of the system
        """
        inverse_inertia = np.linalg.inv(self.inertia_matrix)
        part1 = np.dot(inverse_inertia, angular_vel)
        part2 = np.dot(self.inertia_matrix, angular_vel)
        cross = np.cross(part1, part2)
        value = desired_acc + cross
        return np.dot(self.inertia_matrix, value)

    def angular_rotation_matrix(self, euler_angles):
        """Rotation matix to assist conversion between angular velocity
        and derivative of Euler angles
        Use inverse of the matrix to convert from angular velocity to euler rates
        """
        [phi, theta, psi] = euler_angles
        m = np.array([[1, 0,            -np.sin(theta)],
                      [0, np.cos(phi),  np.cos(theta) * np.sin(phi)],
                      [0, -np.sin(psi), np.cos(theta) * np.cos(phi)]
                      ])
        return m

    def rotation_matrix(self, euler_angles):
        [phi, theta, psi] = euler_angles
        cphi = np.cos(phi)
        sphi = np.sin(phi)
        cthe = np.cos(theta)
        sthe = np.sin(theta)
        cpsi = np.cos(psi)
        spsi = np.sin(psi)

        m = np.array([[cthe * cpsi, sphi * sthe * cpsi - cphi * spsi, cphi * sthe * cpsi + sphi * spsi],
                      [cthe * spsi, sphi * sthe * spsi + cphi * cpsi, cphi * sthe * spsi - sphi * cpsi],
                      [-sthe,       cthe * sphi,                      cthe * cphi]])
        return m

    @property
    def inertia_matrix(self):
        return np.diag(self.config['inertia'])

    def update_state(self, piecewise_args):
        """Update the current state of the system. It runs the model and updates
        its state to self._dt seconds.

        Parameters
        ----------
        piecewise_args : array
            It contains the parameters that are needed to run each section
            of the flight. It is an array of tuples.
            [(ct1, da1, t1), (ct2, da2, t2), ..., (ctn, dan, tn)]

            ct : float
                The collective thrust generated by all motors
            da : numpy.array
                The desired angular acceleration that the system should achieve.
                This should be of form [dp/dt, dq/dt, dr/dt]
            t: float
                Time for which this section should run and should be atleast twice
                self._dt
        """
        if self.save_state:
            overall_time = 0
            for section in piecewise_args:
                overall_time += section[2]

            overall_length = len(np.arange(0, overall_time, self._dt)) - (len(piecewise_args) - 1)
            # Allocate space for storing state of all sections
            final_state = np.zeros([overall_length + 100, 12])
        else:
            final_state = []

        # Create variable to maintain state between integration steps
        self._euler_dot = np.zeros(3)
        index = 0

        for section in piecewise_args:
            (coll_thrust, desired_angular_acc, t) = section
            if t < (2 * self._dt):
                # raise ValueError('t=%s is less than (2 * self._dt)=%s' % (t, self._dt))
                continue

            ts = np.arange(0, t, self._dt)
            state = np.concatenate((self.state['position'], self.state['velocity'],
                                    self.state['orientation'], self.state['ang_velocity']))
            output = odeint(self._integrator, state, ts, args=(coll_thrust, desired_angular_acc))

            output_length = len(output)
            # Update the system state
            [self.state['position'], self.state['velocity'],
             self.state['orientation'], self.state['ang_velocity']] = np.split(output[output_length - 1], 4)

            if self.save_state:
                # Update the final state
                final_state[index:(index + output_length)] = output

                # Update the index to one less than current length, because the
                # first state is equal to the final state of previous section
                index = index + output_length - 1

        return final_state

    def _integrator(self, state, t, coll_thrust, desired_angular_acc):
        """Callback function for scipy.integrate.odeint.

        Parameters
        ----------
        state : numpy.array
            Entire state of the system. The contents of the array is
            [x, y, z, xdot, ydot, zdot, phi, theta, psi, p, q, r]
        t : float
            Time

        Returns
        -------
        numpy.array
            The derivatives of the input state.
            [xdot, ydot, zdot, xddot, yddot, zddot, phidot, thetadot, psidot, pdot, qdot, rdot]
        """
        # Position inertial frame [x, y, z]
        pos = state[:3]
        # Velocity inertial frame [x, y, z]
        velocity = state[3:6]
        euler = state[6:9]
        # Angular velocity omega = [p, q, r]
        omega = state[9:12]

        # Derivative of euler angles [dphi/dt, dtheta/dt, dpsi/dt]
        euler_dot = self._euler_dot

        # omega = self.dt_eulerangles_to_angular_velocity(euler_dot, euler)
        moments = self.moments(desired_angular_acc, omega)
        thrusts = self.motor_thrust(moments, coll_thrust)
        # Acceleration in inertial frame
        acc = self.acceleration(thrusts, euler)

        omega_dot = self.angular_acceleration(omega, thrusts)
        euler_dot = self.angular_velocity_to_dt_eulerangles(omega, euler)
        self._euler_dot = euler_dot
        # [velocity : acc : euler_dot : omega_dot]
        # print 'Vel', velocity
        # print 'Acc', acc
        # print 'Euler dot', euler_dot
        # print 'omdega dot', omega_dot
        return np.concatenate((velocity, acc, euler_dot, omega_dot))
